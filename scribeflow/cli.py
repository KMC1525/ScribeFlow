"""Linha de comando do ScribeFlow — o comando `scribeflow` (e o atalho `scribe`):

    scribeflow [run]                      abre o ScribeFlow no navegador (padrão)
    scribeflow models list|search|pull|use|rm   modelos de texto do Hugging Face
    scribeflow engine status|install      o motor de IA local (llama.cpp)
    scribeflow projects list|export|import      projetos (JSON)
    scribeflow update | folder | doctor | version
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any, List, Optional

from . import __version__

REPO_ZIP = "https://github.com/KMC1525/ScribeFlow/archive/refs/heads/main.zip"
WHEELS = "https://abetlen.github.io/llama-cpp-python/whl/"
DEFAULT_PORT = 8791
BANNER = r"""
  ____            _ _         _____ _
 / ___|  ___ _ __(_) |__   __|  ___| | _____      __
 \___ \ / __| '__| | '_ \ / _ \ |_  | |/ _ \ \ /\ / /
  ___) | (__| |  | | |_) |  __/  _| | | (_) \ V  V /
 |____/ \___|_|  |_|_.__/ \___|_|   |_|\___/ \_/\_/     v{version}
"""


def system_lang() -> str:
    for var in ("SCRIBEFLOW_LANG", "LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        v = (os.environ.get(var) or "").lower()
        if v and v not in ("c", "posix"):
            return "pt" if v.startswith("pt") else "en"
    try:
        import locale

        return "pt" if (locale.getdefaultlocale()[0] or "").lower().startswith("pt") else "en"
    except Exception:  # noqa: BLE001
        return "en"


def L(pt: str, en: str) -> str:
    """Texto do terminal: português primeiro, inglês quando o sistema não está em português."""
    return pt if system_lang() == "pt" else en


def stdio_safe() -> None:
    """O terminal nunca derruba o comando por causa de um caractere: com a saída redirecionada o Windows usa uma codificação sem ✓ ⚠ …; o que ela não representa vira «?»."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")   # type: ignore[union-attr]
        except (AttributeError, OSError, ValueError):
            pass


def _store(args: argparse.Namespace) -> Any:
    from .storage import Store

    return Store(Path(args.home).expanduser() if getattr(args, "home", None) else None)


def _fmt_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return str(n)


# --------------------------------------------------------------------------- run
def cmd_run(args: argparse.Namespace) -> int:
    from .server import make_server

    store = _store(args)
    host = args.host or "127.0.0.1"
    start = int(args.port or os.environ.get("SCRIBEFLOW_PORT") or DEFAULT_PORT)
    httpd = None
    for port in range(start, start + 20):   # porta ocupada: tenta a seguinte
        try:
            httpd, app = make_server(host, port, store)
            break
        except OSError:
            continue
    if httpd is None:
        print(L("Não consegui abrir nenhuma porta entre {a} e {b}.", "Could not open any port between {a} and {b}.").format(a=start, b=start + 19), file=sys.stderr)
        return 1
    url = f"http://{'localhost' if host in ('127.0.0.1', '0.0.0.0') else host}:{port}/"
    print(BANNER.format(version=__version__))
    print(L("ScribeFlow rodando em {u}   (Ctrl+C para sair)", "ScribeFlow running at {u}   (Ctrl+C to quit)").format(u=url))
    print(L("Dados em: {h}", "Data in: {h}").format(h=store.home))
    from . import llm as llmmod

    if llmmod.resolve_model(store) is None:
        print(L("⚠ Nenhum modelo de texto baixado ainda: abra Configurações → Modelo de texto (IA), ou rode:  scribeflow models pull",
                "⚠ No text model downloaded yet: open Settings → Text model (AI), or run:  scribeflow models pull"))
    if not llmmod.llama_available()["installed"]:
        print(L("⚠ O motor de IA local não está instalado. Rode:  scribeflow engine install", "⚠ The local AI engine is not installed. Run:  scribeflow engine install"))
    if host not in ("127.0.0.1", "localhost", "::1"):
        print(L("⚠ Escutando fora deste computador ({h}): qualquer pessoa na sua rede pode abrir o ScribeFlow.", "⚠ Listening beyond this computer ({h}): anyone on your network can open ScribeFlow.").format(h=host))
    if not args.no_browser and os.environ.get("SCRIBEFLOW_NO_BROWSER", "") in ("", "0"):
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        httpd.server_close()
    return 0


# --------------------------------------------------------------------------- modelos
def cmd_models(args: argparse.Namespace) -> int:
    from . import hf, llm as llmmod
    from .net import ProviderError
    from .storage import DEFAULT_MODEL_FILE, DEFAULT_MODEL_REPO
    from .util import hardware_info

    store = _store(args)
    s = store.get_settings()
    token = s["hf"]["token"]
    mdir = Path(store.models_dir)
    act = args.action or "list"
    try:
        if act == "list":
            active = llmmod.resolve_model(store, s)
            rows = hf.local_models(mdir)
            if not rows:
                print(L("Nenhum modelo baixado. O padrão é {r}. Baixe com:  scribeflow models pull", "No model downloaded. The default is {r}. Download with:  scribeflow models pull").format(r=DEFAULT_MODEL_REPO))
            for m in rows:
                print(("* " if active and active.name == m["name"] else "  ") + f"{m['name']}  ({_fmt_bytes(m['size'])}" + (f", {m['repo']}" if m.get("repo") else "") + ")")
            print(L("Pasta: {d}", "Folder: {d}").format(d=mdir))
        elif act == "search":
            if not args.name:
                print(L("Uso: scribeflow models search TERMO", "Usage: scribeflow models search TERM"), file=sys.stderr)
                return 2
            for r in hf.search(args.name, token, limit=20):
                print(f"{r['id']}  ⬇ {r['downloads']:,}  ♥ {r['likes']}")
        elif act == "pull":
            repo = hf.parse_repo(args.name or s["model"]["repo"] or DEFAULT_MODEL_REPO)
            if not repo:
                print(L("Repositório inválido (use dono/nome).", "Invalid repository (use owner/name)."), file=sys.stderr)
                return 2
            info = hf.repo_info(repo, token)
            if not info["text"]:
                print(L("«{r}» não é um modelo de geração de texto: o ScribeFlow só usa modelos de texto.", "“{r}” is not a text-generation model: ScribeFlow only uses text models.").format(r=repo), file=sys.stderr)
                return 1
            files = hf.list_files(repo, token, float(hardware_info().get("ram_gb") or 0))
            if not files:
                print(L("«{r}» não tem arquivos GGUF.", "“{r}” has no GGUF files.").format(r=repo), file=sys.stderr)
                return 1
            want = args.file or (s["model"]["file"] if repo == s["model"]["repo"] else "")
            opt = next((f for f in files if want and (f["name"] == want or Path(f["name"]).name == want or f["quant"].lower() == want.lower())), None) or next((f for f in files if f["recommended"]), files[0])
            print(L("Baixando {n} ({s}) de {r}…", "Downloading {n} ({s}) from {r}…").format(n=opt["name"], s=_fmt_bytes(opt["size"]), r=repo))
            last = [0.0]

            def progress(done: int, total: int) -> None:
                if time.time() - last[0] > 0.5 or done >= total:
                    last[0] = time.time()
                    print(f"\r  {_fmt_bytes(done)} / {_fmt_bytes(total)}  ({100 * done // max(1, total)}%)   ", end="", flush=True)

            path = hf.download_many(repo, opt["files"], mdir, token, opt["sizes"], progress)
            print()
            store.save_settings({"model": {"active": path.name}})
            print(L("Pronto: {p} (agora é o modelo em uso).", "Done: {p} (now the active model).").format(p=path))
        elif act == "use":
            name = Path(args.name or "").name
            if name not in {m["name"] for m in hf.local_models(mdir)}:
                print(L("Modelo não encontrado: veja  scribeflow models list", "Model not found: see  scribeflow models list"), file=sys.stderr)
                return 1
            store.save_settings({"model": {"active": name}})
            print(L("Modelo em uso: {n}", "Active model: {n}").format(n=name))
        elif act in ("rm", "remove", "delete"):
            name = Path(args.name or "").name
            if name not in {m["name"] for m in hf.local_models(mdir)}:
                print(L("Modelo não encontrado.", "Model not found."), file=sys.stderr)
                return 1
            hf.delete_local(mdir, name)
            if s["model"]["active"] == name:
                store.save_settings({"model": {"active": ""}})
            print(L("Apagado: {n}", "Deleted: {n}").format(n=name))
        else:
            print(L("Ação desconhecida: {a}", "Unknown action: {a}").format(a=act), file=sys.stderr)
            return 2
    except ProviderError as exc:
        print(L("Erro: {e}", "Error: {e}").format(e=exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n" + L("Interrompido (o download continua de onde parou na próxima vez).", "Interrupted (the download resumes where it stopped next time)."))
        return 130
    return 0


# --------------------------------------------------------------------------- motor de IA local (llama.cpp)
def _backend_auto() -> str:
    if sys.platform == "darwin":
        return "metal"
    if shutil.which("nvidia-smi"):
        return "cuda"
    return "cpu"


def cmd_engine(args: argparse.Namespace) -> int:
    from . import llm as llmmod

    info = llmmod.llama_available()
    if (args.action or "status") == "status":
        if info["installed"]:
            print(L("Motor instalado: llama-cpp-python {v} ({g})", "Engine installed: llama-cpp-python {v} ({g})").format(v=info["version"] or "?", g=L("com GPU", "with GPU") if info["gpu"] else L("só CPU", "CPU only")))
        else:
            print(L("Motor NÃO instalado. Instale com:  scribeflow engine install", "Engine NOT installed. Install with:  scribeflow engine install"))
            if info.get("error"):
                print("  " + info["error"])
        return 0
    backend = args.backend if args.backend and args.backend != "auto" else _backend_auto()
    py = sys.executable
    base = [py, "-m", "pip", "install"] + (["--upgrade"] if args.upgrade else [])
    index = {"cpu": "cpu", "metal": "metal", "cuda": "cu124"}.get(backend, "cpu")
    print(L("Instalando o motor de IA local (llama-cpp-python, {b})…", "Installing the local AI engine (llama-cpp-python, {b})…").format(b=backend))
    # 1) wheel pré-compilado (rápido, sem compilador)
    code = subprocess.call(base + ["--only-binary=llama-cpp-python", "--prefer-binary", "--extra-index-url", WHEELS + index, "llama-cpp-python"])
    if code == 0:
        print(L("Motor instalado.", "Engine installed."))
        return 0
    # 2) compila pelo PyPI (precisa de compilador C/C++ e cmake)
    print(L("Não achei um pacote pré-compilado para este computador: vou compilar (precisa de compilador C/C++ e cmake; pode levar vários minutos)…",
            "No prebuilt package for this computer: building from source (needs a C/C++ compiler and cmake; may take several minutes)…"))
    env = dict(os.environ)
    flags = {"metal": "-DGGML_METAL=on", "cuda": "-DGGML_CUDA=on"}.get(backend, "")
    if flags and "CMAKE_ARGS" not in env:
        env["CMAKE_ARGS"] = flags
    code = subprocess.call(base + ["llama-cpp-python"], env=env)
    if code != 0:
        print(L("Falhou. Veja https://github.com/abetlen/llama-cpp-python#installation (no Windows instale o «Build Tools for Visual Studio»; no macOS rode  xcode-select --install ;  no Linux  sudo apt install build-essential cmake).",
                "Failed. See https://github.com/abetlen/llama-cpp-python#installation (on Windows install “Build Tools for Visual Studio”; on macOS run  xcode-select --install ;  on Linux  sudo apt install build-essential cmake)."), file=sys.stderr)
        return code
    print(L("Motor instalado.", "Engine installed."))
    return 0


# --------------------------------------------------------------------------- projetos
def cmd_projects(args: argparse.Namespace) -> int:
    from .projects import ProjectError, json_bytes

    store = _store(args)
    pm = store.projects
    act = args.action or "list"
    try:
        if act == "list":
            rows = pm.list()
            if not rows:
                print(L("Nenhum projeto ainda.", "No projects yet."))
            for p in rows:
                print(f"{p['id']}  {p['name']}  ({p['words']} {L('palavras', 'words')})")
        elif act == "export":
            if not args.name:
                print(L("Uso: scribeflow projects export ID [-o arquivo.json]", "Usage: scribeflow projects export ID [-o file.json]"), file=sys.stderr)
                return 2
            data = json_bytes(pm.export_json(args.name))
            if args.out:
                Path(args.out).write_bytes(data)
                print(L("Exportado: {f}", "Exported: {f}").format(f=args.out))
            else:
                sys.stdout.buffer.write(data + b"\n")
        elif act == "import":
            if not args.name:
                print(L("Uso: scribeflow projects import arquivo.json", "Usage: scribeflow projects import file.json"), file=sys.stderr)
                return 2
            meta = pm.import_json(json.loads(Path(args.name).read_text(encoding="utf-8-sig")))
            print(L("Importado: {i}  {n}", "Imported: {i}  {n}").format(i=meta["id"], n=meta["name"]))
        else:
            print(L("Ação desconhecida: {a}", "Unknown action: {a}").format(a=act), file=sys.stderr)
            return 2
    except ProjectError as exc:
        print(exc.message, file=sys.stderr)
        return 1
    except (OSError, ValueError) as exc:
        print(L("Erro: {e}", "Error: {e}").format(e=exc), file=sys.stderr)
        return 1
    return 0


# --------------------------------------------------------------------------- manutenção
def cmd_update(args: argparse.Namespace) -> int:
    print(L("Atualizando o ScribeFlow (seus projetos e modelos não são tocados)…", "Updating ScribeFlow (your projects and models are not touched)…"))
    code = subprocess.call([sys.executable, "-m", "pip", "install", "--upgrade", REPO_ZIP])
    print(L("Pronto. Feche o ScribeFlow e abra de novo.", "Done. Close ScribeFlow and open it again.") if code == 0 else L("Falhou.", "Failed."))
    return code


def cmd_folder(args: argparse.Namespace) -> int:
    path = _store(args).home
    print(path)
    try:
        if sys.platform == "darwin":
            subprocess.call(["open", str(path)])
        elif os.name == "nt":
            os.startfile(str(path))   # type: ignore[attr-defined]
        elif shutil.which("xdg-open"):
            subprocess.call(["xdg-open", str(path)])
    except OSError:
        pass
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    from . import hf, llm as llmmod
    from .storage import DEFAULT_MODEL_REPO
    from .util import hardware_info

    store = _store(args)
    hw = hardware_info()
    info = llmmod.llama_available()
    ok, bad = "✓", "⚠"
    print(f"ScribeFlow {__version__}  ·  Python {hw['python']}  ·  {hw['os']} {hw['arch']}")
    print(f"{ok} " + L("{c} núcleos, {r} GB de RAM", "{c} cores, {r} GB RAM").format(c=hw["cpus"], r=hw["ram_gb"] or "?") + (f", GPU: {hw['gpu']}" if hw["gpu"] else ""))
    print(f"{ok if info['installed'] else bad} " + (L("Motor de IA: llama-cpp-python {v}", "AI engine: llama-cpp-python {v}").format(v=info["version"]) if info["installed"] else L("Motor de IA ausente:  scribeflow engine install", "AI engine missing:  scribeflow engine install")))
    models = hf.local_models(Path(store.models_dir))
    print(f"{ok if models else bad} " + (L("{n} modelo(s) em {d}", "{n} model(s) in {d}").format(n=len(models), d=store.models_dir) if models else L("Nenhum modelo baixado (padrão: {r}):  scribeflow models pull", "No model downloaded (default: {r}):  scribeflow models pull").format(r=DEFAULT_MODEL_REPO)))
    print(f"{ok} " + L("Dados: {h} ({n} projeto(s))", "Data: {h} ({n} project(s))").format(h=store.home, n=len(store.projects.list())))
    for w in store.storage_warnings:
        print(f"{bad} {w}")
    return 0


def cmd_version(args: argparse.Namespace) -> int:
    print(f"ScribeFlow {__version__}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="scribeflow", description=L("ScribeFlow: editor de textos com IA local (modelos de texto do Hugging Face).", "ScribeFlow: a text editor with local AI (Hugging Face text models)."))
    p.add_argument("--home", help=L("pasta de dados (padrão: ~/.scribeflow)", "data folder (default: ~/.scribeflow)"))
    p.add_argument("--host", help=L("endereço (padrão: 127.0.0.1)", "address (default: 127.0.0.1)"))
    p.add_argument("--port", type=int, help=L("porta (padrão: 8791)", "port (default: 8791)"))
    p.add_argument("--no-browser", action="store_true", help=L("não abrir o navegador", "do not open the browser"))
    sub = p.add_subparsers(dest="cmd")
    r = sub.add_parser("run", help=L("abre o ScribeFlow no navegador (padrão)", "opens ScribeFlow in the browser (default)"))
    r.set_defaults(fn=cmd_run)
    m = sub.add_parser("models", help=L("modelos de texto: list | search TERMO | pull [dono/nome] [--file ARQ] | use ARQ | rm ARQ", "text models: list | search TERM | pull [owner/name] [--file FILE] | use FILE | rm FILE"))
    m.add_argument("action", nargs="?", default="list")
    m.add_argument("name", nargs="?")
    m.add_argument("--file", help=L("arquivo ou quantização (ex.: Q4_K_M)", "file or quantization (e.g. Q4_K_M)"))
    m.set_defaults(fn=cmd_models)
    e = sub.add_parser("engine", help=L("motor de IA local: status | install [--backend cpu|cuda|metal] [--upgrade]", "local AI engine: status | install [--backend cpu|cuda|metal] [--upgrade]"))
    e.add_argument("action", nargs="?", default="status")
    e.add_argument("--backend", choices=["auto", "cpu", "cuda", "metal"], default="auto")
    e.add_argument("--upgrade", action="store_true")
    e.set_defaults(fn=cmd_engine)
    pr = sub.add_parser("projects", help=L("projetos: list | export ID [-o arq.json] | import arq.json", "projects: list | export ID [-o file.json] | import file.json"))
    pr.add_argument("action", nargs="?", default="list")
    pr.add_argument("name", nargs="?")
    pr.add_argument("-o", "--out")
    pr.set_defaults(fn=cmd_projects)
    for name, fn, hlp in (("update", cmd_update, L("atualiza o ScribeFlow", "updates ScribeFlow")), ("folder", cmd_folder, L("abre a pasta de dados", "opens the data folder")),
                          ("doctor", cmd_doctor, L("diagnóstico do ambiente", "environment diagnostics")), ("version", cmd_version, L("mostra a versão", "shows the version"))):
        sub.add_parser(name, help=hlp).set_defaults(fn=fn)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    stdio_safe()
    args = build_parser().parse_args(argv)
    fn = getattr(args, "fn", cmd_run)
    return int(fn(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
