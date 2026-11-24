"""Utilitários sem dependências: ids, JSON atômico, coerção, hardware e TLS."""
from __future__ import annotations

import json
import os
import platform
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def home_dir() -> Path:
    """Pasta de dados do usuário (SCRIBEFLOW_HOME ou ~/.scribeflow). Atualizar ou desinstalar nunca apaga o que há aqui."""
    custom = os.environ.get("SCRIBEFLOW_HOME")
    base = Path(custom).expanduser() if custom else Path.home() / ".scribeflow"
    base.mkdir(parents=True, exist_ok=True)
    return base


def new_id(prefix: str = "") -> str:
    return prefix + secrets.token_hex(5)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def slugify(text: str, default: str = "item", max_len: int = 48) -> str:
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return (text[:max_len].strip("-")) or default


def safe_filename(name: str, default: str = "file") -> str:
    """Nome de arquivo seguro (sem diretórios, sem caracteres de controle)."""
    name = os.path.basename(str(name or "").replace("\\", "/"))
    name = re.sub(r"[\x00-\x1f<>:\"|?*]", "_", name).strip(". ")
    return name[:120] or default


def read_json(path: Path, default: Any = None) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def write_json(path: Path, data: Any, private: bool = False) -> None:
    """Escrita atômica: grava em arquivo temporário e troca."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        if private:
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def num(value: Any, default: float, lo: Optional[float] = None, hi: Optional[float] = None) -> float:
    """Converte para número com limites; valores inválidos viram `default`."""
    try:
        out = float(value)
        if out != out or out in (float("inf"), float("-inf")):
            raise ValueError
    except (TypeError, ValueError):
        out = float(default)
    if lo is not None:
        out = max(lo, out)
    if hi is not None:
        out = min(hi, out)
    return out


def text(value: Any, default: str = "", max_len: int = 4000) -> str:
    if value is None:
        return default
    s = str(value).strip()
    return s[:max_len] if s else default


def deep_merge(base: dict, patch: dict) -> dict:
    """Mescla `patch` em `base` recursivamente (retorna novo dict)."""
    out = dict(base)
    for key, val in (patch or {}).items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], val)
        else:
            out[key] = val
    return out


class Cancelled(Exception):
    """A execução foi cancelada pelo usuário."""


# --------------------------------------------------------------------------- hardware
_HW_CACHE: Optional[dict] = None


def _run_out(cmd: list, timeout: float = 6.0) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout or ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _ram_gb() -> Optional[float]:
    try:
        if sys.platform.startswith("linux"):
            for line in Path("/proc/meminfo").read_text().splitlines():
                if line.startswith("MemTotal:"):
                    return round(int(line.split()[1]) / 1024 / 1024, 1)
        elif sys.platform == "darwin":
            out = _run_out(["sysctl", "-n", "hw.memsize"]).strip()
            return round(int(out) / 1024 ** 3, 1) if out.isdigit() else None
        elif os.name == "nt":
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("l", ctypes.c_ulong), ("p", ctypes.c_ulong), ("tp", ctypes.c_ulonglong), ("ap", ctypes.c_ulonglong), ("tf", ctypes.c_ulonglong),
                            ("af", ctypes.c_ulonglong), ("tv", ctypes.c_ulonglong), ("av", ctypes.c_ulonglong), ("ae", ctypes.c_ulonglong)]

            st = MS()
            st.l = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))   # type: ignore[attr-defined]
            return round(st.tp / 1024 ** 3, 1)
    except Exception:  # noqa: BLE001
        pass
    return None


def _gpu_name() -> Optional[str]:
    if shutil.which("nvidia-smi"):
        out = _run_out(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"]).strip().splitlines()
        if out:
            return out[0].strip()
    if sys.platform == "darwin" and platform.machine().lower() in ("arm64", "aarch64"):
        return "Apple Silicon (GPU integrada)"
    return None


def hardware_info(refresh: bool = False) -> dict:
    """Resumo do computador: sistema, processador, memória e placa de vídeo (se achar). Só para mostrar e escolher a quantização."""
    global _HW_CACHE
    if _HW_CACHE is not None and not refresh:
        return _HW_CACHE
    ram = _ram_gb()
    _HW_CACHE = {"os": platform.system(), "arch": platform.machine(), "cpus": os.cpu_count() or 1, "ram_gb": ram, "gpu": _gpu_name(), "python": platform.python_version()}
    return _HW_CACHE


# --------------------------------------------------------------------------- certificados HTTPS (macOS com o Python do python.org)
def ssl_context():
    """Contexto TLS para as conexões HTTPS. O Python do python.org no macOS vem sem certificados raiz: aqui, se o contexto padrão não tem nenhum, carregamos os do `certifi`
    (se instalado) ou os do Chaveiro do macOS. Nunca desliga a verificação."""
    import ssl

    ctx = ssl.create_default_context()
    if ctx.cert_store_stats().get("x509_ca", 0) > 0 or os.environ.get("SSL_CERT_FILE") or os.environ.get("SSL_CERT_DIR"):
        return ctx
    try:
        import certifi  # type: ignore

        ctx.load_verify_locations(cafile=certifi.where())
        return ctx
    except Exception:  # noqa: BLE001
        pass
    if sys.platform == "darwin":
        pem = _run_out(["/usr/bin/security", "find-certificate", "-a", "-p", "/System/Library/Keychains/SystemRootCertificates.keychain", "/Library/Keychains/System.keychain"], 30)
        if "BEGIN CERTIFICATE" in pem:
            try:
                ctx.load_verify_locations(cadata=pem)
            except Exception:  # noqa: BLE001
                pass
    return ctx


_NUL, _LONE_SURROGATE = re.compile("\x00"), re.compile("[\ud800-\udfff]")


def clean_json(v: Any, depth: int = 0) -> Any:
    """Texto vindo do JSON sem bytes nulos e sem «surrogates» soltos (que dariam erro 500 ao salvar)."""
    if isinstance(v, str):
        return _LONE_SURROGATE.sub("�", _NUL.sub("", v)) if ("\x00" in v or _LONE_SURROGATE.search(v)) else v
    if depth > 100:
        raise ValueError("JSON aninhado fundo demais")
    if isinstance(v, dict):
        return {(clean_json(k, depth + 1) if isinstance(k, str) else k): clean_json(x, depth + 1) for k, x in v.items()}
    if isinstance(v, list):
        return [clean_json(x, depth + 1) for x in v]
    return v


_THINK_RE = re.compile(r"<think(?:ing)?>.*?</think(?:ing)?>", re.S | re.I)


def strip_reasoning(raw: str) -> str:
    """Tira o «raciocínio» que modelos como Qwen3 escrevem junto da resposta (<think>…</think>). Um <think> ainda aberto esconde o resto;
    um </think> sem abertura (o modelo já começou pensando) descarta o que veio antes."""
    s = _THINK_RE.sub("", raw or "")
    i = s.lower().find("<think")
    if i >= 0:
        s = s[:i]
    j = s.lower().rfind("</think")
    if j >= 0:
        s = s[s.find(">", j) + 1:]
    return s
