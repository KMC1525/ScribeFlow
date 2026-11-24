"""Busca e download de modelos de TEXTO (GGUF) no Hugging Face, sem dependências externas.

O ScribeFlow só usa modelos de geração de texto, e só do Hugging Face. Cada repositório costuma trazer o mesmo modelo em várias **quantizações** (Q2_K … Q8_0, F16): quanto menos bits,
menor o arquivo e a necessidade de RAM (e menor a qualidade). `list_files` identifica a quantização de cada arquivo, junta modelos divididos em partes (`-00001-of-00003.gguf`) numa só
opção, ignora os projetores de visão (`mmproj`) e indica qual cabe na sua RAM; a pessoa escolhe qual baixar.
"""
from __future__ import annotations

import os
import re
import shutil
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import net as http
from .net import ProviderError

#: o Hub (HF_ENDPOINT troca por um espelho; os testes usam um servidor falso local)
HF = (os.environ.get("HF_ENDPOINT") or "https://huggingface.co").rstrip("/")
REPO_RE = re.compile(r"^[A-Za-z0-9][\w.-]{0,95}/[A-Za-z0-9][\w.-]{0,95}$")
FILE_RE = re.compile(r"^[\w][\w .+()=-]{0,200}\.gguf$")
QUANT_RE = re.compile(r"(?<![A-Za-z0-9])((?:IQ|TQ|Q)\d(?:_[A-Z0-9]+)*|BF16|F16|F32|MXFP4)(?![A-Za-z0-9])", re.I)
SHARD_RE = re.compile(r"^(?P<base>.+)-(?P<n>\d{5})-of-(?P<total>\d{5})\.gguf$", re.I)
QUALITY = {1: "very_low", 2: "very_low", 3: "low", 4: "good", 5: "very_good", 6: "high", 8: "lossless"}
PREFERRED = ("Q4_K_M", "Q5_K_M", "Q4_K_S", "Q5_K_S", "Q6_K", "Q4_0", "Q8_0", "Q3_K_L", "Q3_K_M")  # ordem de preferência ao recomendar

#: filtros «pipeline_tag» do Hugging Face que são geração de texto. Modelos multimodais (ex.: Qwen3.5) vêm como «image-text-to-text»: o ScribeFlow usa só a parte de texto deles.
TEXT_TAGS = ("text-generation", "image-text-to-text")
#: o ScribeFlow recusa tudo o que não é geração de texto (imagem, vídeo, som, voz, embeddings…)
REJECT_TAGS = ("text-to-image", "image-to-image", "text-to-video", "image-to-video", "text-to-audio", "text-to-speech", "automatic-speech-recognition", "feature-extraction",
               "sentence-similarity", "image-to-text", "audio-to-audio", "fill-mask", "text-classification", "token-classification", "image-classification", "object-detection", "text-to-3d", "image-to-3d")


def parse_quant(name: str) -> Dict[str, Any]:
    """Quantização de um arquivo pelo nome: {"quant": "Q4_K_M", "bits": 4, "quality": "good"} (vazio se não achar)."""
    base = Path(name).name
    m = SHARD_RE.match(base)
    base = (m.group("base") + ".gguf") if m else base
    found = QUANT_RE.findall(base)
    if not found:
        return {"quant": "", "bits": 0, "quality": ""}
    q = found[-1].upper()
    if q in ("F16", "BF16"):
        return {"quant": q, "bits": 16, "quality": "original"}
    if q == "F32":
        return {"quant": q, "bits": 32, "quality": "original"}
    if q == "MXFP4":
        return {"quant": q, "bits": 4, "quality": "good"}
    bits = int(re.search(r"\d", q).group())
    return {"quant": q, "bits": bits, "quality": QUALITY.get(bits, "good")}


def _headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"} if token else {}


def parse_repo(value: str) -> str:
    """Aceita «dono/nome», o endereço da página (https://huggingface.co/dono/nome[/…]) ou «hf.co/dono/nome». Devolve «dono/nome» ou «»."""
    s = (value or "").strip()
    m = re.match(r"^(?:https?://)?(?:www\.)?(?:huggingface\.co|hf\.co)/([^/\s]+)/([^/\s?#]+)", s, re.I)
    if m:
        s = f"{m.group(1)}/{m.group(2)}"
    return s if REPO_RE.match(s) else ""


# --------------------------------------------------------------------------- consultas à API do Hub: em paralelo e com cache curto
SEARCH_TIMEOUT = 12.0
CACHE_SECONDS = 90.0
_CACHE: Dict[Any, Any] = {}
_CACHE_LOCK = threading.Lock()


def clear_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


def _get_json_cached(url: str, token: str, timeout: float) -> Any:
    """`GET` JSON do Hub com cache de `CACHE_SECONDS`. Só respostas bem-sucedidas entram no cache."""
    key = (id(http.get_json), url, bool(token))
    now = time.time()
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit and now - hit[0] < CACHE_SECONDS:
            return hit[1]
    data = http.get_json(url, _headers(token), timeout=timeout)
    with _CACHE_LOCK:
        if len(_CACHE) >= 128:
            _CACHE.pop(min(_CACHE, key=lambda k: _CACHE[k][0]), None)
        _CACHE[key] = (time.time(), data)
    return data


def _fetch_all(urls: List[str], token: str, timeout: float = SEARCH_TIMEOUT) -> List[Any]:
    """Consulta todas as `urls` ao mesmo tempo: devolve, na mesma ordem, a resposta (JSON) de cada uma ou a exceção `ProviderError` que ela deu."""
    def one(u: str) -> Any:
        try:
            return _get_json_cached(u, token, timeout)
        except ProviderError as exc:
            return exc

    if len(urls) <= 1:
        return [one(u) for u in urls]
    with ThreadPoolExecutor(max_workers=min(8, len(urls))) as ex:
        return list(ex.map(one, urls))


def _author_queries(query: str) -> List[Dict[str, str]]:
    """Consultas extras por autor/perfil (ex.: «unsloth», «bartowski») para achar todos os modelos de um perfil do Hugging Face."""
    q = (query or "").strip()
    if not q or "/" in q or " " in q:
        return []
    return [{"author": q, "search": ""}, {"author": q, "search": q}]


def search(query: str, token: str = "", limit: int = 20) -> List[Dict[str, Any]]:
    """Busca repositórios GGUF de **geração de texto**, do mais baixado para o menos. Aceita buscar por perfil/autor (ex.: «unsloth») e colar «dono/nome» ou o endereço da página."""
    repo = parse_repo(query)
    if repo:   # repositório exato: mostra ele primeiro (a lista de arquivos confere se serve)
        info = repo_info(repo, token)
        return [info]
    found: Dict[str, Dict[str, Any]] = {}
    queries = [{"search": query}] + _author_queries(query)
    answered, failure = False, None
    urls = []
    for tag in TEXT_TAGS:
        for extra in queries:
            params = {**{k: v for k, v in extra.items() if v}, "filter": "gguf", "pipeline_tag": tag, "sort": "downloads", "direction": "-1", "limit": str(max(limit, 30))}
            urls.append(f"{HF}/api/models?{urllib.parse.urlencode(params)}")
    for data in _fetch_all(urls, token):
        if isinstance(data, ProviderError):
            failure = data
            continue
        answered = True
        for m in data if isinstance(data, list) else []:
            mid = (m.get("id") or m.get("modelId")) if isinstance(m, dict) else None
            if isinstance(mid, str) and REPO_RE.match(mid):
                row = found.setdefault(mid, {"id": mid, "downloads": 0, "likes": 0, "pipeline_tag": str(m.get("pipeline_tag") or "")})
                row["downloads"] = max(int(row.get("downloads") or 0), int(m.get("downloads") or 0))
                row["likes"] = max(int(row.get("likes") or 0), int(m.get("likes") or 0))
    if not answered and failure is not None:   # nenhuma consulta chegou ao Hugging Face (sem rede, fora do ar): dizer isso em vez de «nada encontrado»
        raise failure
    return sorted(found.values(), key=lambda m: -m["downloads"])[:limit]


def repo_info(repo: str, token: str = "") -> Dict[str, Any]:
    """Dados de um repositório: {id, downloads, likes, pipeline_tag, gguf, text}. `text` é False quando o repositório é de outro tipo de modelo (imagem, voz, embeddings…)."""
    if not REPO_RE.match(repo or ""):
        raise ProviderError("Repositório inválido (use o formato dono/nome).")
    data = _get_json_cached(f"{HF}/api/models/{repo}", token, SEARCH_TIMEOUT)
    if not isinstance(data, dict):
        raise ProviderError("Resposta inesperada do Hugging Face.")
    tags = [str(t).lower() for t in (data.get("tags") or [])]
    tag = str(data.get("pipeline_tag") or "")
    return {"id": data.get("id") or repo, "downloads": int(data.get("downloads") or 0), "likes": int(data.get("likes") or 0), "pipeline_tag": tag, "gguf": "gguf" in tags,
            "text": tag not in REJECT_TAGS}


def repo_files(repo: str, token: str = "") -> List[Dict[str, Any]]:
    """Todos os arquivos de um repositório do Hugging Face: [{name (caminho), size}]."""
    if not REPO_RE.match(repo or ""):
        raise ProviderError("Repositório inválido (use o formato dono/nome).")
    data = _get_json_cached(f"{HF}/api/models/{repo}/tree/main?recursive=1", token, 20)
    out = []
    for it in data if isinstance(data, list) else []:
        path = it.get("path", "") if isinstance(it, dict) else ""
        if it.get("type") == "file" and path and ".." not in path:
            out.append({"name": path, "size": int((it.get("lfs") or {}).get("size") or it.get("size") or 0)})
    return out


def group_files(raw: List[Dict[str, Any]], ram_gb: float = 0) -> List[Dict[str, Any]]:
    """Agrupa arquivos GGUF em opções de download: junta partes divididas, ignora projetores de visão (mmproj) e marca a recomendada.

    Cada opção: {name (arquivo principal), files (todas as partes), sizes (por parte), size (soma), parts, quant, bits, quality, fits, recommended}.
    """
    groups: Dict[str, Dict[str, Any]] = {}
    for f in raw:
        base = Path(f["name"]).name
        if "mmproj" in base.lower():
            continue
        m = SHARD_RE.match(base)
        key = str(Path(f["name"]).parent / m.group("base")) if m else f["name"]
        g = groups.setdefault(key, {"parts": {}, "total": int(m.group("total")) if m else 1})
        g["parts"][int(m.group("n")) if m else 1] = f
    out = []
    for g in groups.values():
        if len(g["parts"]) != g["total"]:   # partes faltando no repositório: não dá para usar
            continue
        parts = [g["parts"][k] for k in sorted(g["parts"])]
        out.append({"name": parts[0]["name"], "files": [p["name"] for p in parts], "sizes": {p["name"]: p["size"] for p in parts}, "size": sum(p["size"] for p in parts), "parts": len(parts), **parse_quant(parts[0]["name"])})
    out.sort(key=lambda f: (f["size"], f["name"]))
    limit = ram_gb * 0.6 * 1024 ** 3
    for f in out:
        f["fits"] = bool(ram_gb) and f["size"] <= limit
        f["recommended"] = False
    fitting = [f for f in out if f["fits"] and f["quant"]]
    pick = None
    for q in PREFERRED:   # a melhor entre as preferidas que cabem; senão a maior que cabe até 6 bits; senão a menor de todas
        pick = next((f for f in fitting if f["quant"] == q and f["bits"] <= 6), None)
        if pick:
            break
    pick = pick or next(iter(sorted([f for f in fitting if f["bits"] <= 6], key=lambda f: -f["size"])), None) or (out[0] if out else None)
    if pick:
        pick["recommended"] = True
    return out


def list_files(repo: str, token: str = "", ram_gb: float = 0) -> List[Dict[str, Any]]:
    files = [f for f in repo_files(repo, token) if f["name"].lower().endswith(".gguf") and FILE_RE.match(Path(f["name"]).name)]
    return group_files(files, ram_gb)


def shard_files(models_dir: Path, name: str) -> List[Path]:
    """Todos os arquivos de um modelo local: ele mesmo ou, se for dividido, todas as partes."""
    m = SHARD_RE.match(Path(name).name)
    if not m:
        return [models_dir / Path(name).name]
    total = int(m.group("total"))
    return [models_dir / f"{m.group('base')}-{k:05d}-of-{total:05d}.gguf" for k in range(1, total + 1)]


def local_models(models_dir: Path) -> List[Dict[str, Any]]:
    """Modelos baixados. Um modelo dividido em partes aparece uma vez, com o tamanho total; projetores de visão (mmproj) ficam de fora."""
    out = []
    for p in sorted(Path(models_dir).glob("*.gguf")):
        m = SHARD_RE.match(p.name)
        if m and int(m.group("n")) != 1:
            continue
        if "mmproj" in p.name.lower():
            continue
        parts = shard_files(Path(models_dir), p.name)
        if not all(x.exists() for x in parts):
            continue   # partes faltando: o modelo não carrega
        meta = read_meta(Path(models_dir), p.name)
        out.append({"name": p.name, "size": sum(x.stat().st_size for x in parts), "parts": len(parts), "mtime": max(x.stat().st_mtime for x in parts), "repo": meta.get("repo", ""), **parse_quant(p.name)})
    return out


def meta_path(models_dir: Path, name: str) -> Path:
    return Path(models_dir) / (Path(name).name + ".json")


def read_meta(models_dir: Path, name: str) -> Dict[str, Any]:
    """De qual repositório do Hugging Face o arquivo veio (gravado ao lado do modelo no download)."""
    from .util import read_json

    d = read_json(meta_path(models_dir, name), {})
    return d if isinstance(d, dict) else {}


def write_meta(models_dir: Path, name: str, repo: str) -> None:
    from .util import now_iso, write_json

    try:
        write_json(meta_path(models_dir, name), {"repo": repo, "file": Path(name).name, "downloaded": now_iso()})
    except OSError:
        pass


def delete_local(models_dir: Path, name: str) -> int:
    """Apaga um modelo local (e todas as partes). Devolve quantos arquivos saíram."""
    n = 0
    base = Path(models_dir).resolve()
    for p in shard_files(base, name):
        target = p.resolve()
        if target.parent != base or not target.name.lower().endswith(".gguf"):
            continue
        for extra in (target, target.with_name(target.name + ".part"), target.with_name(target.name + ".part.seg"), meta_path(base, target.name)):
            try:
                extra.unlink()
                n += 1
            except FileNotFoundError:
                pass
    return n


#: conexões simultâneas por arquivo (configuração hf.connections; ver dl.py)
CONNECTIONS = 4


def configure(hf_settings: Dict[str, Any]) -> None:
    global CONNECTIONS
    from . import dl

    CONNECTIONS = dl.clamp_connections((hf_settings or {}).get("connections", dl.DEFAULT_CONNECTIONS))


def download(repo: str, filename: str, models_dir: Path, token: str = "", progress: Optional[Callable[[int, int], None]] = None, cancelled: Callable[[], bool] = lambda: False, connections: int = 0) -> Path:
    """Baixa um .gguf do repositório para `models_dir` (com várias conexões, retomada e novas tentativas). O arquivo só ganha o nome final depois de conferido (começa com «GGUF»)."""
    if not REPO_RE.match(repo or "") or not FILE_RE.match(Path(filename).name) or ".." in filename:
        raise ProviderError("Repositório ou arquivo inválido.")
    dest = Path(models_dir) / Path(filename).name
    part = dest.with_suffix(dest.suffix + ".part")
    url = f"{HF}/{repo}/resolve/main/{urllib.parse.quote(filename)}"
    from . import dl

    dl.fetch(url, part, _headers(token), connections or CONNECTIONS, progress, cancelled)
    _verify(part, dest.name)
    os.replace(part, dest)
    return dest


def _verify(part: Path, name: str) -> None:
    """Confere o arquivo baixado ANTES de ele ganhar o nome final: um .gguf tem que começar com «GGUF». Uma página de erro, de login ou de portal de rede (Wi-Fi de hotel…) não vira «modelo»."""
    try:
        with open(part, "rb") as fh:
            head = fh.read(4)
    except OSError as exc:
        raise ProviderError(f"Não consegui conferir o arquivo baixado: {exc}") from None
    if head != b"GGUF":
        part.unlink(missing_ok=True)
        try:
            from . import dl

            dl._sidecar(part).unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
        raise ProviderError(f"O arquivo «{name}» baixado não é um modelo GGUF (não começa com «GGUF»: provavelmente é uma página de erro, de login ou de uma rede com portal). Apaguei o arquivo; "
                            "tente baixar de novo (confira a conexão, o token do Hugging Face e se o repositório exige aceitar uma licença).")


def download_many(repo: str, filenames: List[str], models_dir: Path, token: str = "", sizes: Optional[Dict[str, int]] = None, progress: Optional[Callable[[int, int], None]] = None,
                  cancelled: Callable[[], bool] = lambda: False) -> Path:
    """Baixa uma opção (um arquivo ou todas as partes de um modelo dividido) com progresso somado. Devolve o arquivo principal."""
    if not filenames or len(filenames) > 99:
        raise ProviderError("Nada para baixar.")
    models_dir = Path(models_dir)
    models_dir.mkdir(parents=True, exist_ok=True)
    sizes = sizes or {}
    total = sum(int(sizes.get(f, 0)) for f in filenames)
    if total:
        pending = total - sum((models_dir / Path(f).name).stat().st_size for f in filenames if (models_dir / Path(f).name).exists())
        if shutil.disk_usage(models_dir).free < max(0, pending) * 1.02 + (50 << 20):
            raise ProviderError("Sem espaço em disco suficiente para este modelo.")
    base = 0
    first: Optional[Path] = None
    for f in filenames:
        done_file = models_dir / Path(f).name
        if sizes.get(f) and done_file.exists() and done_file.stat().st_size == int(sizes[f]):   # parte já baixada (retomada)
            base += int(sizes[f])
            first = first or done_file
            if progress:
                progress(base, total)
            continue

        def prog(done: int, tot: int, base: int = base) -> None:
            if progress:
                progress(base + done, total or (base + tot))

        path = download(repo, f, models_dir, token, prog, cancelled)
        first = first or path
        base += int(sizes.get(f, 0)) or path.stat().st_size
    if first is not None:
        write_meta(models_dir, first.name, repo)
    return first  # type: ignore[return-value]
