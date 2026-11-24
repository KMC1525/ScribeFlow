"""O modelo de texto local do ScribeFlow: um GGUF do Hugging Face rodando dentro do próprio programa (llama.cpp, pela biblioteca `llama-cpp-python`).

Não há provedor de nuvem, chave de API nem servidor externo: só o arquivo que a pessoa baixou. Uma geração por vez (fila com trava), o modelo fica na memória
enquanto se usa e é descarregado depois de `idle_unload_min` minutos parado. A janela de contexto vem das configurações (padrão 16K tokens).
"""
from __future__ import annotations

import gc
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from . import hf
from .net import ProviderError
from .util import Cancelled, strip_reasoning

INSTALL_HINT = ("O motor de IA local não está instalado. Rode no terminal:  scribeflow engine install  "
                "(ou:  pip install llama-cpp-python). Depois reinicie o ScribeFlow.")


class ContextTooLong(ValueError):
    """O texto não cabe na janela de contexto do modelo (um ValueError de propósito: vira uma mensagem clara, sem derrubar nada)."""


def llama_available() -> Dict[str, Any]:
    """O llama-cpp-python está instalado? Qual versão e se ele manda camadas para a placa de vídeo."""
    try:
        import llama_cpp  # type: ignore
    except Exception as exc:  # noqa: BLE001  (ImportError, ou falha ao carregar a biblioteca nativa)
        return {"installed": False, "version": "", "gpu": False, "error": str(exc)[:200]}
    gpu = False
    try:
        gpu = bool(llama_cpp.llama_supports_gpu_offload())
    except Exception:  # noqa: BLE001
        pass
    return {"installed": True, "version": str(getattr(llama_cpp, "__version__", "")), "gpu": gpu, "error": ""}


def resolve_model(store: Any, settings: Optional[dict] = None) -> Optional[Path]:
    """O arquivo do modelo em uso: o escolhido nas configurações (se existe), senão o padrão, senão o primeiro que houver. None se não há nenhum baixado."""
    s = settings or store.get_settings()
    cfg = s["model"]
    mdir = Path(store.models_dir)
    local = {m["name"] for m in hf.local_models(mdir)}
    for name in (cfg.get("active"), cfg.get("file")):
        if name and name in local:
            return mdir / name
    return (mdir / sorted(local)[0]) if local else None


def fit_budget(n_ctx: int, max_new: int) -> int:
    """Quantos tokens sobram para o prompt depois de reservar a resposta (e uma pequena margem do modelo de chat)."""
    return max(256, int(n_ctx) - int(max_new) - 64)


class LocalLLM:
    """Mantém um modelo carregado por vez e serializa as gerações."""

    def __init__(self, store: Any):
        self.store = store
        self.lock = threading.RLock()       # uma geração por vez
        self._llm: Any = None
        self._key: Tuple = ()
        self._path: Optional[Path] = None
        self._last_use = 0.0
        self._timer: Optional[threading.Timer] = None
        self.last_info: Dict[str, Any] = {}   # o que foi carregado por último (para a tela de configurações)

    # ------------------------------------------------------------------ estado
    def status(self) -> Dict[str, Any]:
        s = self.store.get_settings()
        path = resolve_model(self.store, s)
        lib = llama_available()
        return {"engine": lib, "model": path.name if path else "", "model_path": str(path) if path else "", "loaded": self._llm is not None, "n_ctx": int(s["model"]["n_ctx"]),
                "loaded_info": self.last_info if self._llm is not None else {}}

    def unload(self) -> None:
        with self.lock:
            self._llm = None
            self._key = ()
            self._path = None
            if self._timer:
                self._timer.cancel()
                self._timer = None
        gc.collect()

    def _schedule_unload(self, minutes: int) -> None:
        if self._timer:
            self._timer.cancel()
            self._timer = None
        if minutes <= 0:
            return

        def check() -> None:
            if time.time() - self._last_use >= minutes * 60 - 1 and self.lock.acquire(blocking=False):
                try:
                    self.unload()
                finally:
                    self.lock.release()
            else:
                self._schedule_unload(minutes)

        self._timer = threading.Timer(minutes * 60, check)
        self._timer.daemon = True
        self._timer.start()

    # ------------------------------------------------------------------ carregar
    def _load(self, settings: dict) -> Any:
        try:
            from llama_cpp import Llama  # type: ignore
        except Exception:  # noqa: BLE001
            raise ProviderError(INSTALL_HINT) from None
        path = resolve_model(self.store, settings)
        if path is None:
            raise ProviderError("Nenhum modelo de texto baixado. Abra Configurações → Modelo de texto (IA) e baixe um (o padrão é " + settings["model"]["repo"] + ").")
        cfg = settings["model"]
        threads = int(cfg["threads"]) or max(1, (os.cpu_count() or 2) - 1)
        key = (str(path), int(cfg["n_ctx"]), int(cfg["gpu_layers"]), threads)
        if self._llm is not None and self._key == key:
            return self._llm
        self._llm = None
        self._key = ()
        gc.collect()
        ngl = int(cfg["gpu_layers"])
        attempts = [ngl] + ([0] if ngl != 0 else [])
        last: Optional[Exception] = None
        llm = None
        for layers in attempts:
            try:
                llm = Llama(model_path=str(path), n_ctx=int(cfg["n_ctx"]), n_threads=threads, n_gpu_layers=layers, use_mmap=True, verbose=False)
                break
            except Exception as exc:  # noqa: BLE001  (sem memória na placa, arquitetura nova demais para a versão instalada…)
                last = exc
        if llm is None:
            msg = str(last or "")[:300]
            hint = " Atualize o motor:  scribeflow engine install --upgrade  (modelos novos podem exigir um llama.cpp mais recente)." if "arch" in msg.lower() or "load" in msg.lower() else ""
            raise ProviderError(f"Não consegui carregar o modelo {path.name}: {msg}{hint}")
        self._llm, self._key, self._path = llm, key, path
        self.last_info = {"model": path.name, "n_ctx": int(cfg["n_ctx"]), "n_gpu_layers": layers, "n_threads": threads}
        return llm

    # ------------------------------------------------------------------ tokens
    def count_tokens(self, text_: str) -> int:
        """Tokens de um texto no modelo carregado; sem modelo carregado, uma estimativa (~3 caracteres por token)."""
        llm = self._llm
        if llm is not None:
            try:
                return len(llm.tokenize(text_.encode("utf-8"), add_bos=False, special=False))
            except Exception:  # noqa: BLE001
                pass
        return len(text_) // 3 + 1

    # ------------------------------------------------------------------ gerar
    @staticmethod
    def _prompt(llm: Any, messages: List[dict], thinking: bool) -> Optional[Tuple[str, List[str]]]:
        """Modelos com «modo de pensar» (Qwen3…): o modelo de chat do GGUF aceita `enable_thinking`. Montamos o prompt nós mesmos para DESLIGAR o pensamento
        (a biblioteca não repassa esse parâmetro). Devolve (prompt, parada) ou None se o modelo não tem esse recurso (então vale o caminho normal)."""
        try:
            tpl = (llm.metadata or {}).get("tokenizer.chat_template") or ""
            if "enable_thinking" not in tpl:
                return None
            from jinja2.sandbox import ImmutableSandboxedEnvironment  # type: ignore

            def tok(i: int) -> str:
                try:
                    return llm.detokenize([i]).decode("utf-8", "ignore") if i >= 0 else ""
                except Exception:  # noqa: BLE001
                    return ""

            def boom(msg: str) -> None:
                raise ValueError(msg)

            env = ImmutableSandboxedEnvironment(trim_blocks=True, lstrip_blocks=True)
            eos = tok(llm.token_eos())
            prompt = env.from_string(tpl).render(messages=messages, add_generation_prompt=True, enable_thinking=bool(thinking), bos_token=tok(llm.token_bos()), eos_token=eos,
                                                 raise_exception=boom, strftime_now=lambda f: time.strftime(f))
            return prompt, ([eos] if eos else [])
        except Exception:  # noqa: BLE001
            return None

    def generate(self, messages: List[dict], max_tokens: int = 1024, temperature: float = 0.7, top_p: float = 0.9, repeat_penalty: float = 1.05,
                 on_text: Optional[Callable[[str], None]] = None, cancelled: Callable[[], bool] = lambda: False, json_schema: Optional[dict] = None) -> Tuple[str, str]:
        """Gera a resposta a `messages` ({role, content} com texto). Devolve (texto sem o «raciocínio», motivo da parada: «stop» ou «length»).
        `on_text` recebe o texto acumulado durante a geração (para mostrar o progresso). `json_schema` força a resposta a ser um JSON desse formato (gramática do llama.cpp)."""
        settings = self.store.get_settings()
        with self.lock:
            llm = self._load(settings)
            thinking = bool(settings["model"]["thinking"])
            self._last_use = time.time()
            n_ctx = int(llm.n_ctx())
            used = sum(self.count_tokens(str(m.get("content") or "")) + 8 for m in messages)
            max_tokens = int(max(32, min(max_tokens, n_ctx - used - 16)))
            if used + 48 > n_ctx:
                raise ContextTooLong(f"O texto e as instruções ({used} tokens) não cabem na janela de contexto do modelo ({n_ctx}). Aumente a janela em Configurações → Modelo de texto (IA), "
                                     "ou selecione um trecho menor.")
            rendered = self._prompt(llm, messages, thinking)
            acc: List[str] = []
            stop_reason = "stop"
            kw: Dict[str, Any] = dict(max_tokens=max_tokens, temperature=temperature, top_p=top_p, repeat_penalty=repeat_penalty, stream=True)
            if json_schema:
                try:
                    import json as _json

                    from llama_cpp import LlamaGrammar  # type: ignore

                    kw["grammar"] = LlamaGrammar.from_json_schema(_json.dumps(json_schema))
                except Exception:  # noqa: BLE001  (versão sem gramática JSON: segue sem, o chamador valida o JSON)
                    pass
            try:
                if rendered:
                    stream: Iterator[Any] = llm.create_completion(rendered[0], stop=rendered[1] or None, **kw)
                    pick = lambda ch: ch["choices"][0].get("text") or ""   # noqa: E731
                else:
                    stream = llm.create_chat_completion(messages=messages, **kw)
                    pick = lambda ch: (ch["choices"][0].get("delta") or {}).get("content") or ""   # noqa: E731
                for ch in stream:
                    if cancelled():
                        raise Cancelled()
                    piece = pick(ch)
                    fr = ch["choices"][0].get("finish_reason")
                    if fr:
                        stop_reason = "length" if fr == "length" else "stop"
                    if piece:
                        acc.append(piece)
                        if on_text:
                            on_text(strip_reasoning("".join(acc)))
            except (Cancelled, ProviderError):
                raise
            except Exception as exc:  # noqa: BLE001  (ValueError de contexto, RuntimeError do llama.cpp…)
                msg = str(exc)
                if "context" in msg.lower() or "exceed" in msg.lower():
                    raise ContextTooLong("O texto não cabe na janela de contexto do modelo. Aumente a janela em Configurações → Modelo de texto (IA).") from None
                raise ProviderError(f"O modelo local falhou: {msg[:300]}") from None
            finally:
                self._last_use = time.time()
                self._schedule_unload(int(settings["model"]["idle_unload_min"]))
        return strip_reasoning("".join(acc)).strip(), stop_reason
