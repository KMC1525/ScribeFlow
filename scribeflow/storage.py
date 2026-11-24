"""Persistência em disco do ScribeFlow: configurações, projetos e modelos locais. Tudo é JSON/arquivos comuns dentro de SCRIBEFLOW_HOME (padrão ~/.scribeflow):

    settings.json
    projects/<id>/project.json       um projeto (texto, system prompt geral, formatação…)
    projects/<id>/history/           pontos de retorno do texto
    projects/<id>/exports/           .docx, .md, .txt e .html gerados
    models/                          modelos GGUF de texto baixados do Hugging Face
"""
from __future__ import annotations

import copy
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from .projects import ProjectStore
from .uiprefs import DEFAULT_UI, normalize_ui
from .util import deep_merge, home_dir, read_json, write_json

#: o modelo padrão (Hugging Face) e a janela de contexto padrão
DEFAULT_MODEL_REPO = "darrellbest/Qwen3.5-2B-Heretic-GGUF"
DEFAULT_MODEL_FILE = "Qwen3.5-2B-Heretic-Q4_K_M.gguf"
DEFAULT_N_CTX = 16384
MAX_N_CTX = 1 << 20
MIN_N_CTX = 512

DEFAULT_SETTINGS: Dict[str, Any] = {
    "language": "auto",   # auto | pt-BR | en
    "ui": DEFAULT_UI,     # aparência: tema, cor de destaque, escala, densidade…
    "model": {
        "repo": DEFAULT_MODEL_REPO,       # de onde baixar o modelo padrão
        "file": DEFAULT_MODEL_FILE,       # qual arquivo (quantização) do repositório
        "active": "",                     # arquivo .gguf em uso (vazio = o padrão, se estiver baixado; senão o primeiro que houver)
        "n_ctx": DEFAULT_N_CTX,           # janela de contexto em tokens (16K por padrão; ajustável nas configurações)
        "gpu_layers": -1,                 # camadas na placa de vídeo: -1 = o máximo possível, 0 = só CPU
        "threads": 0,                     # 0 = automático
        "idle_unload_min": 10,            # descarrega o modelo da memória depois de N minutos parado (0 = nunca)
        "thinking": False,                # modelos que «pensam» (Qwen3…): desligado = respostas diretas e mais rápidas
    },
    "scriber": {
        "type": "romance", "language": "pt-BR", "content": "free",
        "expand_words": 150, "dialogue_words": 60, "undo_keep": 25,
        "spellcheck": True, "autosave": True, "web": False,
    },
    "web": {"engine": "auto", "results": 5, "read_pages": 2},   # busca na web do editor (DuckDuckGo → Wikipédia; sem chave)
    "server": {"max_upload_mb": 50},
    "storage": {"models_dir": ""},   # "" = a pasta padrão (~/.scribeflow/models); um disco externo, outro disco…
    "hf": {"token": "", "connections": 4},   # connections: conexões simultâneas por download (1 a 8; ver dl.py)
}

# Caminhos (dentro de settings) que contêm segredos e nunca são enviados ao navegador.
SECRET_PATHS = [("hf", "token")]


def conform(defaults: Any, value: Any) -> Any:
    """Força `value` a ter a «forma» de `defaults`: onde o padrão é um objeto, o valor precisa ser um objeto (senão volta ao padrão); onde o padrão é número/texto/booleano, um valor de
    outro tipo é descartado. Um settings.json editado à mão (ou uma chamada de API errada) não derruba a tela inteira."""
    if not isinstance(defaults, dict):
        return value
    out = dict(value) if isinstance(value, dict) else {}
    for key, dv in defaults.items():
        if key not in out:
            out[key] = copy.deepcopy(dv)
        elif isinstance(dv, dict):
            out[key] = conform(dv, out[key]) if isinstance(out[key], dict) else copy.deepcopy(dv)
        elif isinstance(dv, bool):
            if not isinstance(out[key], bool):
                out[key] = bool(out[key]) if isinstance(out[key], (int, float)) else dv
        elif isinstance(dv, (int, float)):
            if isinstance(out[key], bool) or not isinstance(out[key], (int, float)):
                out[key] = dv
        elif isinstance(dv, str):
            if not isinstance(out[key], str):
                out[key] = dv
    return out


def _normalize(s: Dict[str, Any]) -> None:
    """Limites dos valores numéricos e dos textos que viram nomes de arquivo."""
    m = s["model"]
    m["n_ctx"] = int(max(MIN_N_CTX, min(MAX_N_CTX, m["n_ctx"]))) if m["n_ctx"] else DEFAULT_N_CTX
    m["gpu_layers"] = int(max(-1, min(999, m["gpu_layers"])))
    m["threads"] = int(max(0, min(256, m["threads"])))
    m["idle_unload_min"] = int(max(0, min(1440, m["idle_unload_min"])))
    for k in ("active", "file"):
        v = Path(str(m.get(k) or "")).name
        m[k] = v if (v.lower().endswith(".gguf") or not v) else ""
    sc = s["scriber"]
    sc["expand_words"] = int(max(10, min(3000, sc["expand_words"])))
    sc["dialogue_words"] = int(max(10, min(3000, sc["dialogue_words"])))
    sc["undo_keep"] = int(max(5, min(100, sc["undo_keep"])))
    if sc["content"] not in ("free", "sfw"):
        sc["content"] = "free"
    w = s["web"]
    w["results"] = int(max(1, min(10, w["results"])))
    w["read_pages"] = int(max(0, min(5, w["read_pages"])))
    if w["engine"] not in ("auto", "duckduckgo", "wikipedia"):
        w["engine"] = "auto"
    s["server"]["max_upload_mb"] = int(max(1, min(2000, s["server"]["max_upload_mb"])))
    s["hf"]["connections"] = int(max(1, min(8, s["hf"]["connections"])))
    if s["language"] not in ("auto", "pt-BR", "en"):
        s["language"] = "auto"


def _get_path(data: dict, path: tuple) -> Any:
    cur: Any = data
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
    return cur


def _set_path(data: dict, path: tuple, value: Any) -> None:
    cur = data
    for key in path[:-1]:
        cur = cur.setdefault(key, {})
    cur[path[-1]] = value


class Store:
    def __init__(self, home: Optional[Path] = None):
        self.home = Path(home) if home else home_dir()
        self.home.mkdir(parents=True, exist_ok=True)
        self.settings_path = self.home / "settings.json"
        self.default_models_dir = self.home / "models"
        self.default_models_dir.mkdir(parents=True, exist_ok=True)
        self.projects = ProjectStore(self.home / "projects", self)
        self._models_dir = self.default_models_dir
        self.storage_warnings: list = []
        self._lock = threading.RLock()
        self.apply_storage(self.get_settings())

    # ------------------------------------------------------------------ onde guardar os modelos
    @property
    def models_dir(self) -> Path:
        return self._models_dir

    @models_dir.setter
    def models_dir(self, value: Any) -> None:
        self._models_dir = Path(value)

    def apply_storage(self, settings: dict) -> None:
        """Passa a usar a pasta de `settings["storage"]` para os modelos. Pasta inacessível → a padrão, com aviso (um disco externo desligado não quebra nada)."""
        chosen = str((settings.get("storage") or {}).get("models_dir") or "")
        self.storage_warnings = []
        self._models_dir = self.default_models_dir
        if not chosen:
            return
        p = Path(chosen).expanduser()
        try:
            p.mkdir(parents=True, exist_ok=True)
            probe = p / ".scribeflow-write-probe"
            probe.write_bytes(b"")
            probe.unlink()
            self._models_dir = p
        except OSError:
            self.storage_warnings.append(f"A pasta de modelos {chosen} não está acessível (dispositivo desconectado?). Usando a pasta padrão até ela voltar.")

    # ------------------------------------------------------------------ settings
    def get_settings(self) -> dict:
        saved = read_json(self.settings_path, {}) or {}
        merged = conform(DEFAULT_SETTINGS, deep_merge(copy.deepcopy(DEFAULT_SETTINGS), saved if isinstance(saved, dict) else {}))
        _normalize(merged)
        merged["ui"] = normalize_ui(merged.get("ui"))   # valor inválido (API/edição manual) volta ao padrão em vez de quebrar a interface
        return merged

    def save_settings(self, patch: dict) -> dict:
        """Mescla `patch` nas configurações. Segredos: "" ou ausente = manter; null = apagar; texto = definir."""
        with self._lock:
            current = self.get_settings()
            patch = copy.deepcopy(patch or {})
            for path in SECRET_PATHS:
                if _get_path(patch, path) == "":
                    _set_path(patch, path, _get_path(current, path))
            patch.pop("version", None)
            merged = conform(DEFAULT_SETTINGS, deep_merge(current, patch))
            _normalize(merged)
            merged["ui"] = normalize_ui(merged.get("ui"))
            for path in SECRET_PATHS:
                if _get_path(merged, path) is None:
                    _set_path(merged, path, "")
            write_json(self.settings_path, merged, private=True)
            self.apply_storage(merged)
            return merged

    def public_settings(self) -> dict:
        """Configurações para o navegador: o token vira só «tem token?»."""
        s = self.get_settings()
        out = copy.deepcopy(s)
        out["hf"]["token"] = ""
        out["hf"]["token_set"] = bool(s["hf"]["token"])
        return out
