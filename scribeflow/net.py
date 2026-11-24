"""Cliente HTTP mínimo (urllib) com JSON. Sem dependências externas."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional

from . import __version__
from .util import ssl_context

USER_AGENT = f"ScribeFlow/{__version__} (+https://github.com/KMC1525/ScribeFlow)"
RETRYABLE = (429, 502, 503, 529)


class ProviderError(Exception):
    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


def is_local_host(host: str) -> bool:
    """localhost, 127.x, ::1, redes privadas (192.168.x, 10.x…) e nomes .local: a própria máquina ou a rede de casa. Usado pela busca na web para nunca ler páginas locais (SSRF)."""
    import ipaddress

    host = (host or "").strip("[]").lower()
    if host in ("localhost", "ip6-localhost") or host.endswith((".local", ".lan", ".home.arpa", ".internal", ".ts.net")):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    if ip.version == 4 and ip in ipaddress.ip_network("100.64.0.0/10"):
        return True
    return ip.is_loopback or ip.is_private or ip.is_link_local


def _read_error(exc: urllib.error.HTTPError) -> str:
    try:
        body = exc.read().decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        body = ""
    try:
        data = json.loads(body)
        err = data.get("error", data)
        if isinstance(err, dict):
            err = err.get("message") or json.dumps(err, ensure_ascii=False)
        return str(err)[:600]
    except Exception:  # noqa: BLE001
        return body[:600]


def request(url: str, payload: Optional[dict] = None, headers: Optional[Dict[str, str]] = None, method: Optional[str] = None, timeout: float = 120, raw_body: Optional[bytes] = None, retries: int = 0):
    """Abre uma requisição e devolve a resposta (file-like). Levanta ProviderError. `retries`: tentativas extras quando o servidor está sobrecarregado (429/5xx)."""
    hdrs = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    hdrs.update(headers or {})
    data = raw_body
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    try:
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method or ("POST" if data is not None else "GET"))
    except ValueError:
        raise ProviderError(f"Endereço inválido: «{url[:120]}».") from None
    for attempt in range(retries + 1):
        try:
            return urllib.request.urlopen(req, timeout=timeout, context=ssl_context())
        except urllib.error.HTTPError as exc:
            msg = _read_error(exc) or str(exc.reason)
            if exc.code in RETRYABLE and attempt < retries:
                try:
                    wait = float(exc.headers.get("Retry-After") or 0)
                except (TypeError, ValueError):
                    wait = 0
                time.sleep(min(max(wait, 0.5 * (attempt + 1)), 8.0))
                continue
            raise ProviderError(msg, status=exc.code) from None
        except urllib.error.URLError as exc:
            raise ProviderError(f"Não foi possível conectar a {urllib.parse.urlsplit(url).netloc or url[:60]}: {exc.reason}") from None
        except (TimeoutError, OSError) as exc:
            raise ProviderError(f"Falha de rede: {exc}") from None
    raise ProviderError("Falha de rede.")  # pragma: no cover


def get_json(url: str, headers: Optional[Dict[str, str]] = None, timeout: float = 30) -> Any:
    with request(url, headers=headers, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))
