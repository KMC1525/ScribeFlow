"""Servidor HTTP do ScribeFlow (somente biblioteca padrão).

- Serve a WebUI (scribeflow/web).
- API JSON em /api/*, com Server-Sent Events para o progresso das ações da IA e dos downloads de modelos.
- Escuta apenas em 127.0.0.1 por padrão; valida Host/Origin (anti DNS-rebinding/CSRF). O token do Hugging Face nunca chega ao navegador.
"""
from __future__ import annotations

import json
import mimetypes
import os
import re
import socket
import time
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import __version__, hf, llm as llmmod, schema as S, spell, stats, uiprefs
from .ai import ScribeAI
from .jobs import HttpError, Job, JobManager  # noqa: F401  (reexportados)
from .net import ProviderError
from .projects import EXPORT_FORMATS, MAX_IMPORT, ProjectError, json_bytes
from .storage import DEFAULT_MODEL_FILE, DEFAULT_MODEL_REPO, DEFAULT_SETTINGS, Store
from .util import Cancelled, clean_json as _clean_json, hardware_info, safe_filename, slugify, text, write_json

WEB_DIR = Path(__file__).parent / "web"
PID = r"(?P<pid>[\w-]+)"
DOC_LIMIT = 28 * 1024 * 1024
MIME = {
    ".js": "text/javascript; charset=utf-8", ".mjs": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8", ".json": "application/json; charset=utf-8", ".md": "text/markdown; charset=utf-8",
    ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".ico": "image/x-icon", ".txt": "text/plain; charset=utf-8",
    ".webp": "image/webp", ".webmanifest": "application/manifest+json",
}
EXPORT_MIME = {"docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "md": "text/markdown; charset=utf-8", "txt": "text/plain; charset=utf-8", "html": "text/html; charset=utf-8"}


def _disk_version() -> str:
    """Versão instalada em disco agora. Difere de `__version__` quando o ScribeFlow foi atualizado e este processo ainda é o antigo."""
    try:
        m = re.search(r"__version__\s*=\s*[\"']([^\"']+)[\"']", (Path(__file__).parent / "__init__.py").read_text(encoding="utf-8"))
        return m.group(1) if m else __version__
    except OSError:
        return __version__


def guess_mime(path: str) -> str:
    ext = Path(path).suffix.lower()
    return MIME.get(ext) or mimetypes.guess_type(path)[0] or "application/octet-stream"


# --------------------------------------------------------------------------- aplicação
class App:
    def __init__(self, store: Store, bind_host: str = "127.0.0.1"):
        self.store = store
        self.pm = store.projects
        self.jobs = JobManager()
        self.llm = llmmod.LocalLLM(store)
        self.bind_host = bind_host
        self.routes: List[Tuple[str, "re.Pattern[str]", Callable]] = []
        hf.configure(store.get_settings()["hf"])
        self._register()

    # ----- roteamento
    def add(self, method: str, pattern: str, fn: Callable) -> None:
        def wrapped(req: "Request", **kw: Any) -> None:
            try:
                fn(req, **kw)
            except ProjectError as exc:
                raise HttpError(exc.status, exc.message) from None
            except ProviderError as exc:
                raise HttpError(502, str(exc)) from None
            except ValueError as exc:
                raise HttpError(400, str(exc)) from None

        self.routes.append((method, re.compile("^" + pattern + "$"), wrapped))

    def dispatch(self, req: "Request") -> bool:
        for method, rx, fn in self.routes:
            if method != req.method and not (req.method == "HEAD" and method == "GET"):   # HEAD = GET sem corpo
                continue
            m = rx.match(req.path)
            if m:
                fn(req, **m.groupdict())
                return True
        return False

    def host_allowed(self, host_header: str) -> bool:
        host = (host_header or "").strip().lower()
        if host.startswith("["):
            name = host[1:host.find("]")] if "]" in host else host
        else:
            name = host.split(":")[0]
        if name in ("localhost", "127.0.0.1", "::1"):
            return True
        return self.bind_host not in ("127.0.0.1", "localhost", "::1")   # exposto na rede por escolha do usuário (scribeflow --host)

    # ------------------------------------------------------------------ rotas
    def _register(self) -> None:
        a = self.add
        a("GET", r"/api/state", self.r_state)
        a("GET", r"/api/catalog", lambda req: req.json(S.catalog()))
        a("GET", r"/api/editor/status", self.r_editor_status)
        a("GET", r"/api/settings", lambda req: req.json(self.store.public_settings()))
        a("PUT", r"/api/settings", self.r_settings_put)
        a("GET", r"/api/settings/export", self.r_settings_export)
        a("POST", r"/api/settings/import", self.r_settings_import)
        a("POST", r"/api/settings/reset", self.r_settings_reset)

        a("GET", r"/api/jobs", self.r_jobs)
        a("GET", r"/api/jobs/(?P<jid>[\w-]+)", self.r_job_get)
        a("GET", r"/api/jobs/(?P<jid>[\w-]+)/events", self.r_job_events)
        a("POST", r"/api/jobs/(?P<jid>[\w-]+)/cancel", self.r_job_cancel)

        # modelo de texto (Hugging Face): estado, busca, arquivos, download, escolher, apagar
        a("GET", r"/api/models", self.r_models)
        a("POST", r"/api/models/use", self.r_model_use)
        a("POST", r"/api/models/test", self.r_model_test)
        a("POST", r"/api/models/unload", lambda req: (self.llm.unload(), req.json({"ok": True})))
        a("DELETE", r"/api/models/local/(?P<name>[^/]+)", self.r_model_delete)
        a("GET", r"/api/hf/search", self.r_hf_search)
        a("GET", r"/api/hf/files", self.r_hf_files)
        a("POST", r"/api/hf/download", self.r_hf_download)

        # projetos (o mesmo sistema do OpenFlow)
        a("GET", r"/api/projects", self.r_list)
        a("POST", r"/api/projects", self.r_create)
        a("POST", r"/api/projects/import", self.r_import_json)
        a("GET", rf"/api/projects/{PID}", self.r_get)
        a("PUT", rf"/api/projects/{PID}", lambda req, pid: req.json(self.pm.update_meta(pid, self._body(req))))
        a("DELETE", rf"/api/projects/{PID}", lambda req, pid: (self.pm.delete(pid), req.json({"ok": True})))
        a("POST", rf"/api/projects/{PID}/duplicate", lambda req, pid: req.json(self.pm.duplicate(pid, text(self._body(req).get("name"), "", 100)), 201))
        a("GET", rf"/api/projects/{PID}/export.json", self.r_export_json)
        a("GET", rf"/api/projects/{PID}/document", lambda req, pid: req.json(self.pm.get_doc(pid)))
        a("PUT", rf"/api/projects/{PID}/document", self.r_save_doc)
        a("GET", rf"/api/projects/{PID}/history", lambda req, pid: req.json({"items": self.pm.history(pid)}))
        a("POST", rf"/api/projects/{PID}/history/restore", lambda req, pid: req.json(self.pm.restore(pid, text(self._body(req).get("id"), "", 60))))
        a("POST", rf"/api/projects/{PID}/snapshot", lambda req, pid: req.json({"id": self.pm.snapshot(pid, text(self._body(req).get("label"), "manual", 100))}))
        a("GET", rf"/api/projects/{PID}/sources", lambda req, pid: req.json({"sources": self.pm.get_sources(pid)}))
        a("PUT", rf"/api/projects/{PID}/sources", lambda req, pid: req.json({"sources": self.pm.save_sources(pid, self._body(req).get("sources"))}))
        a("POST", rf"/api/projects/{PID}/import", self.r_import_file)
        a("GET", rf"/api/projects/{PID}/exports", lambda req, pid: req.json({"items": self.pm.list_exports(pid), "formats": list(EXPORT_FORMATS)}))
        a("POST", rf"/api/projects/{PID}/export", self.r_export)
        a("GET", rf"/api/projects/{PID}/exports/(?P<fname>[\w .+@()%-]+)", self.r_export_get)
        a("DELETE", rf"/api/projects/{PID}/exports/(?P<fname>[\w .+@()%-]+)", lambda req, pid, fname: (self.pm.delete_export(pid, urllib.parse.unquote(fname)), req.json({"ok": True})))

        # ortografia (sem IA), estatísticas, tipografia, busca na web
        a("POST", r"/api/proofread", self.r_proofread)
        a("POST", r"/api/stats", self.r_stats)
        a("POST", r"/api/typography", self.r_typography)
        a("POST", r"/api/web/search", self.r_search)
        a("POST", r"/api/web/read", self.r_search_read)

        # IA (modelo local)
        a("POST", rf"/api/projects/{PID}/ai/edit", self.r_ai_edit)
        a("POST", rf"/api/projects/{PID}/ai/proofread", self.r_ai_proofread)

    # ----- helpers
    @staticmethod
    def _body(req: "Request", limit: int = 8 * 1024 * 1024) -> Dict[str, Any]:
        if not hasattr(req, "_sf_body"):
            b = req.body_json(limit)
            req._sf_body = b if isinstance(b, dict) else {}   # type: ignore[attr-defined]
        return req._sf_body   # type: ignore[attr-defined]

    def _hf_token(self) -> str:
        return str(self.store.get_settings()["hf"].get("token") or "")

    # ----- estado / configurações
    def r_state(self, req: "Request") -> None:
        req.json({"version": __version__, "disk_version": _disk_version(), "hardware": hardware_info(), "home": str(self.store.home), "settings": self.store.public_settings(),
                  "model": self.model_state(), "warnings": list(self.store.storage_warnings)})

    def r_editor_status(self, req: "Request") -> None:
        """O que o editor precisa saber: a IA local está pronta? Há dicionário do sistema (hunspell/aspell) para cada idioma?"""
        m = self.model_state()
        ready = bool(m["active"] and m["engine"]["installed"])
        req.json({"text": {"ai": ready, "label": "ScribeFlow", "model": m["active"].replace(".gguf", "") if m["active"] else "", "engine": m["engine"]["installed"]},
                  "dictionaries": {lang: spell.dictionary_available(lang) for lang in S.LANGUAGES}})

    def r_settings_put(self, req: "Request") -> None:
        body = req.body_json()
        if not isinstance(body, dict):
            raise HttpError(400, "JSON inválido")
        if isinstance(body.get("hf"), dict):
            body["hf"].pop("token_set", None)   # flag somente-leitura que o navegador devolve
        self.store.save_settings(body)
        hf.configure(self.store.get_settings()["hf"])
        req.json(self.store.public_settings())

    def r_settings_export(self, req: "Request") -> None:
        """Baixa as configurações como arquivo, sem o token do Hugging Face."""
        req.bytes(json_bytes(uiprefs.export_settings(self.store.get_settings())), "application/json; charset=utf-8")

    def r_settings_import(self, req: "Request") -> None:
        try:
            patch = uiprefs.import_patch(req.body_json())
        except ValueError as exc:
            raise HttpError(400, str(exc))
        self.store.save_settings(patch)
        req.json({"imported": sorted(patch), "settings": self.store.public_settings()})

    def r_settings_reset(self, req: "Request") -> None:
        """Volta uma seção das configurações ao padrão (ui, scriber, model). O token do Hugging Face nunca é tocado."""
        import copy

        body = req.body_json()
        section = str(body.get("section") or "")
        if section not in uiprefs.RESETTABLE:
            raise HttpError(400, "Seção inválida. Opções: " + ", ".join(uiprefs.RESETTABLE))
        with self.store._lock:
            current = self.store.get_settings()
            current[section] = copy.deepcopy(DEFAULT_SETTINGS[section])
            if section == "ui":
                current["ui"]["welcome_done"] = True   # restaurar a aparência não reabre as boas-vindas
            write_json(self.store.settings_path, current, private=True)
        req.json(self.store.public_settings())

    # ----- tarefas em segundo plano
    def r_jobs(self, req: "Request") -> None:
        """As tarefas em segundo plano (as que rodam primeiro). `?status=running` filtra; `?kind=download` filtra pelo começo do tipo."""
        want = (req.query.get("status", [""])[0] or "").strip()
        kind = (req.query.get("kind", [""])[0] or "").strip()
        with self.jobs.lock:
            items = list(self.jobs.jobs.values())
        items = [j for j in items if (not want or j.status == want) and (not kind or j.kind.startswith(kind))]
        items.sort(key=lambda j: (j.status != "running", -j.created))
        req.json({"jobs": [{"id": j.id, "kind": j.kind, "status": j.status, "events": j.total, "created": j.created, "meta": j.meta} for j in items[:50]]})

    def r_job_get(self, req: "Request", jid: str) -> None:
        job = self.jobs.get(jid)
        if not job:
            raise HttpError(404, "Tarefa não encontrada")
        req.json({"id": job.id, "kind": job.kind, "status": job.status, "events": job.total, "meta": job.meta})

    def r_job_cancel(self, req: "Request", jid: str) -> None:
        job = self.jobs.get(jid)
        if not job:
            raise HttpError(404, "Tarefa não encontrada")
        job.cancel()
        req.json({"ok": True})

    def r_job_events(self, req: "Request", jid: str) -> None:
        job = self.jobs.get(jid)
        if not job:
            raise HttpError(404, "Tarefa não encontrada")
        raw = (req.query.get("from", [""])[0] or "").strip() or str(req.h.headers.get("Last-Event-ID") or "").strip()   # o navegador reconecta sozinho mandando o último id
        idx = int(raw) if raw.isdigit() else 0
        req.sse_start()
        while True:
            with job.cond:
                idx = max(idx, job.base)
                while idx >= job.total and job.status == "running":
                    job.cond.wait(timeout=10)
                    if idx >= job.total and job.status == "running":
                        break
                batch = job.since(idx)
                status = job.status
            for ev in batch:
                req.sse_send(ev, ev.get("seq", idx) + 1)
            idx += len(batch)
            if not batch and status == "running":
                req.sse_comment("keepalive")
            if status != "running" and idx >= job.total:
                req.sse_send({"type": "end", "status": status})
                return

    # ------------------------------------------------------------------ modelo de texto
    def model_state(self) -> Dict[str, Any]:
        s = self.store.get_settings()
        mdir = Path(self.store.models_dir)
        local = hf.local_models(mdir)
        active = llmmod.resolve_model(self.store, s)
        for m in local:
            m["active"] = bool(active and active.name == m["name"])
        names = {m["name"] for m in local}
        return {"local": sorted(local, key=lambda m: (not m["active"], m["name"].lower())), "active": active.name if active else "", "n_ctx": s["model"]["n_ctx"],
                "default": {"repo": DEFAULT_MODEL_REPO, "file": DEFAULT_MODEL_FILE, "installed": DEFAULT_MODEL_FILE in names},
                "configured": {"repo": s["model"]["repo"], "file": s["model"]["file"]}, "models_dir": str(mdir), "engine": llmmod.llama_available(), "loaded": self.llm.status()["loaded"]}

    def r_models(self, req: "Request") -> None:
        req.json(self.model_state())

    def r_model_use(self, req: "Request") -> None:
        name = Path(text(self._body(req).get("name"), "", 300)).name
        if name not in {m["name"] for m in hf.local_models(Path(self.store.models_dir))}:
            raise HttpError(404, "Modelo não encontrado na pasta de modelos.")
        self.store.save_settings({"model": {"active": name}})
        self.llm.unload()
        req.json(self.model_state())

    def r_model_delete(self, req: "Request", name: str) -> None:
        name = Path(urllib.parse.unquote(name)).name
        mdir = Path(self.store.models_dir)
        if name not in {m["name"] for m in hf.local_models(mdir)}:
            raise HttpError(404, "Modelo não encontrado.")
        self.llm.unload()   # solta o arquivo (no Windows um arquivo em uso não pode ser apagado)
        hf.delete_local(mdir, name)
        if self.store.get_settings()["model"]["active"] == name:
            self.store.save_settings({"model": {"active": ""}})
        req.json(self.model_state())

    def r_model_test(self, req: "Request") -> None:
        started = time.time()
        reply, _ = self.llm.generate([{"role": "user", "content": "Reply with the single word: OK"}], max_tokens=24, temperature=0)
        st = self.llm.status()
        req.json({"ok": True, "reply": reply[:80], "ms": int((time.time() - started) * 1000), "model": st["model"], "info": st["loaded_info"]})

    def r_hf_search(self, req: "Request") -> None:
        """Pesquisa modelos de geração de texto (GGUF) no Hugging Face. Aceita «dono/nome» e o endereço da página."""
        q = text(req.query.get("q", [""])[0], "", 200)
        if not q:
            raise HttpError(400, "Digite o que pesquisar.")
        rows = hf.search(q, self._hf_token(), limit=24)
        req.json({"query": q, "results": rows})

    def r_hf_files(self, req: "Request") -> None:
        """As opções de download (quantizações) de um repositório, com a recomendada para a RAM deste computador."""
        repo = hf.parse_repo(req.query.get("repo", [""])[0])
        if not repo:
            raise HttpError(400, "Repositório inválido (use dono/nome).")
        token = self._hf_token()
        info = hf.repo_info(repo, token)
        if not info["text"]:
            raise HttpError(400, f"«{repo}» não é um modelo de geração de texto (tipo: {info['pipeline_tag'] or 'desconhecido'}). O ScribeFlow só usa modelos de texto.")
        files = hf.list_files(repo, token, float(hardware_info().get("ram_gb") or 0))
        if not files:
            raise HttpError(404, f"«{repo}» não tem arquivos GGUF utilizáveis. Procure um repositório de «{repo.split('/')[-1]}» em GGUF (ex.: de unsloth ou bartowski).")
        local = {m["name"] for m in hf.local_models(Path(self.store.models_dir))}
        for f in files:
            f["installed"] = Path(f["name"]).name in local
        req.json({"repo": repo, "info": info, "files": files})

    def r_hf_download(self, req: "Request") -> None:
        body = self._body(req)
        repo = hf.parse_repo(str(body.get("repo") or ""))
        name = text(body.get("name"), "", 300)
        if not repo or not name:
            raise HttpError(400, "Informe o repositório e o arquivo.")
        token = self._hf_token()
        info = hf.repo_info(repo, token)
        if not info["text"]:
            raise HttpError(400, "Este repositório não é de geração de texto: o ScribeFlow só baixa modelos de texto.")
        opt = next((f for f in hf.list_files(repo, token, float(hardware_info().get("ram_gb") or 0)) if f["name"] == name), None)   # o servidor confere o arquivo no Hub: nada vem só do navegador
        if not opt:
            raise HttpError(404, "Arquivo não encontrado nesse repositório.")
        kind = f"download:{repo}/{opt['name']}"
        running = self.jobs.running(kind)
        if running:
            raise HttpError(409, json.dumps({"job_id": running.id}))
        use = body.get("use") is not False
        mdir = Path(self.store.models_dir)

        def work(job: Job) -> Dict[str, Any]:
            last = [0.0, 0, time.time()]

            def progress(done: int, total: int) -> None:
                now = time.time()
                if now - last[0] < 0.3 and done < total:
                    return
                speed = (done - last[1]) / max(0.001, now - last[0]) if last[0] else 0
                last[0], last[1] = now, done
                job.emit({"type": "progress", "done": done, "total": total, "speed": int(speed)})

            job.emit({"type": "start", "repo": repo, "name": opt["name"], "size": opt["size"]})
            path = hf.download_many(repo, opt["files"], mdir, token, opt["sizes"], progress, lambda: job.cancelled)
            if use:
                self.store.save_settings({"model": {"active": path.name}})
                self.llm.unload()
            res = {"name": path.name, "repo": repo, "used": use}
            job.emit({"type": "result", "data": res})
            return res

        job = self.jobs.start(kind, work, {"repo": repo, "name": opt["name"], "label": opt["name"]})
        req.json({"job_id": job.id})

    # ------------------------------------------------------------------ projetos
    def r_list(self, req: "Request") -> None:
        """Todos os projetos. `?q=` pesquisa no nome, na descrição, no system prompt e no texto; `?sort=updated|created|name|words`."""
        q = text(req.query.get("q", [""])[0], "", 120)
        sort = text(req.query.get("sort", ["updated"])[0], "updated", 12)
        req.json(self.pm.list(q, sort if sort in ("updated", "created", "name", "words") else "updated"))

    def r_create(self, req: "Request") -> None:
        b = self._body(req)
        sc = self.store.get_settings()["scriber"]
        meta = self.pm.create(text(b.get("name"), "", 100), b.get("type") if isinstance(b.get("type"), str) else sc["type"], b.get("language") if isinstance(b.get("language"), str) else sc["language"],
                              text(b.get("description"), "", 400), b.get("content") if isinstance(b.get("content"), str) else "", b.get("format"), str(b.get("system_prompt") or ""))
        req.json(meta, 201)

    def r_get(self, req: "Request", pid: str) -> None:
        m = self.pm.meta(pid)
        m["exports"] = self.pm.list_exports(pid)[:10]
        req.json(m)

    def r_save_doc(self, req: "Request", pid: str) -> None:
        b = self._body(req, DOC_LIMIT)
        label = text(b.get("label"), "", 100)
        if isinstance(b.get("blocks"), list):
            res = self.pm.save_doc(pid, blocks=b["blocks"], label=label)
        elif isinstance(b.get("html"), str):
            res = self.pm.save_doc(pid, html_src=b["html"], label=label)
        elif isinstance(b.get("markdown"), str):
            res = self.pm.save_doc(pid, markdown=b["markdown"], label=label)
        else:
            raise HttpError(400, "Envie «html», «blocks» ou «markdown».")
        req.json(res)

    def r_export_json(self, req: "Request", pid: str) -> None:
        """Baixa o projeto inteiro em um único JSON (`?history=0` deixa o histórico de fora)."""
        m = self.pm.meta(pid)
        data = json_bytes(self.pm.export_json(pid, history=req.query.get("history", ["1"])[0] != "0"))
        req.bytes(data, "application/json; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{slugify(m["name"], "projeto", 40)}.scribeflow.json"'})

    def r_import_json(self, req: "Request") -> None:
        """Cria um projeto novo a partir de um JSON exportado pelo ScribeFlow (corpo = o arquivo)."""
        raw = req.body_bytes(MAX_IMPORT)
        try:
            payload = json.loads(raw.decode("utf-8-sig")) if raw else None
        except (ValueError, UnicodeDecodeError, RecursionError):
            raise HttpError(400, "Este arquivo não é um JSON válido.") from None
        try:
            payload = _clean_json(payload)
        except ValueError:
            raise HttpError(400, "JSON aninhado fundo demais.") from None
        meta = self.pm.import_json(payload)
        req.json(self.pm.summary(meta), 201)

    def r_import_file(self, req: "Request", pid: str) -> None:
        name = urllib.parse.unquote(req.headers.get("X-Filename") or req.query.get("name", [""])[0] or "arquivo")
        mode = "append" if req.query.get("mode", ["replace"])[0] == "append" else "replace"
        data = req.body_bytes(MAX_IMPORT)
        if not data:
            raise HttpError(400, "Arquivo vazio.")
        res = self.pm.import_file(pid, name, data, mode)
        res["project"] = self.pm.meta(pid)
        req.json(res)

    def r_export(self, req: "Request", pid: str) -> None:
        fmt = text(self._body(req).get("format"), "docx", 8)
        if fmt not in EXPORT_FORMATS:
            raise HttpError(400, "Formato inválido: " + ", ".join(EXPORT_FORMATS))
        req.json(self.pm.export(pid, fmt))

    def r_export_get(self, req: "Request", pid: str, fname: str) -> None:
        p = self.pm.export_path(pid, urllib.parse.unquote(fname))
        req.file(p, EXPORT_MIME.get(p.suffix.lstrip(".").lower(), "application/octet-stream"), download_name=p.name, headers={"Content-Security-Policy": "sandbox; default-src 'none'; style-src 'unsafe-inline'"})

    # ------------------------------------------------------------------ ortografia / estatísticas / tipografia
    def _paragraphs(self, req: "Request") -> Tuple[List[Any], Dict[str, Any]]:
        b = self._body(req, 16 * 1024 * 1024)
        ps = b.get("paragraphs")
        if not isinstance(ps, list):
            raise HttpError(400, "Envie os parágrafos em «paragraphs».")
        return ps, b

    def r_proofread(self, req: "Request") -> None:
        ps, b = self._paragraphs(req)
        ignore = [x for x in (b.get("ignore") if isinstance(b.get("ignore"), list) else []) if isinstance(x, str)][:500]
        req.json(spell.proofread(ps, b.get("language"), ignore, use_dict=b.get("dictionary") is not False))

    def r_stats(self, req: "Request") -> None:
        ps, b = self._paragraphs(req)
        req.json(stats.analyze(ps, b.get("language")))

    def r_typography(self, req: "Request") -> None:
        ps, b = self._paragraphs(req)
        lang = b.get("language")
        req.json({"paragraphs": [spell.typography(spell.normalize_spacing(str(x), lang), lang) for x in ps[:spell.MAX_PARAS]]})

    # ------------------------------------------------------------------ busca na web
    def r_search(self, req: "Request") -> None:
        from . import websearch

        q = text(self._body(req).get("query"), "", 300)
        if not q:
            raise HttpError(400, "Digite o que pesquisar.")
        try:
            found = websearch.search(q, self.store.get_settings(), ui_lang=(self.store.get_settings().get("language") or "auto"))
        except websearch.SearchError as exc:
            raise HttpError(502, str(exc)) from None
        req.json({"engine": found["engine"], "query": found["query"], "results": [{"title": r["title"][:200], "url": r["url"][:600], "snippet": r["snippet"][:400],
                                                                                    "host": (urllib.parse.urlsplit(r["url"]).hostname or "").removeprefix("www.")} for r in found["results"]]})

    def r_search_read(self, req: "Request") -> None:
        from . import websearch

        url = text(self._body(req).get("url"), "", 600)
        if not websearch.safe_url(url):
            raise HttpError(400, "Só endereços públicos http(s) podem ser lidos.")
        page = websearch.fetch_page(url, 8000)
        if not page.get("text"):
            raise HttpError(502, "Não consegui ler essa página.")
        req.json({"url": url, "title": page.get("title", "")[:200], "text": page["text"][:8000]})

    # ------------------------------------------------------------------ IA
    def _ai_job(self, kind: str, pid: str, req: "Request", method: str) -> None:
        self.pm.meta(pid)
        b = self._body(req, 16 * 1024 * 1024)
        ai_kind = f"ai:{kind}:{pid}"
        running = self.jobs.running(ai_kind)
        if running:
            raise HttpError(409, json.dumps({"job_id": running.id}))
        opts = {"web": b.get("web") is True, "prompt": text(b.get("prompt"), "", 3000), "content": b.get("content") if b.get("content") in ("sfw", "free") else "",
                "sources_text": text(b.get("sources_text"), "", 12000), "body": b}

        def work(job: Job) -> Any:
            return getattr(ScribeAI(self.store, self.pm, self.llm, opts, job), method)(pid)

        job = self.jobs.start(ai_kind, work)
        req.json({"job_id": job.id})

    def r_ai_edit(self, req: "Request", pid: str) -> None:
        b = self._body(req, 16 * 1024 * 1024)
        if not (isinstance(b.get("selection"), str) and b["selection"].strip()) and b.get("action") != "continue":
            raise HttpError(400, "Selecione um trecho do texto (ou use «Continuar»).")
        self._ai_job("edit", pid, req, "edit_text")

    def r_ai_proofread(self, req: "Request", pid: str) -> None:
        self._ai_job("proofread", pid, req, "proofread_ai")

    # ------------------------------------------------------------------ arquivos da interface
    def serve_static(self, req: "Request") -> None:
        rel = urllib.parse.unquote(req.path.lstrip("/")) or "index.html"
        if rel == "sw.js":   # service worker, carimbado com a versão (muda quando o ScribeFlow é atualizado)
            data = (WEB_DIR / "sw.js").read_text(encoding="utf-8").replace("__SCRIBEFLOW_VERSION__", __version__).encode("utf-8")
            req._head(200, "text/javascript; charset=utf-8", len(data), {"Service-Worker-Allowed": "/"})
            if req.method != "HEAD":
                req.h.wfile.write(data)
            return
        if "\x00" in rel:
            raise HttpError(404, "Não encontrado")
        target = (WEB_DIR / rel).resolve()
        if not _under(target, WEB_DIR) or not target.is_file():
            if "." in rel.rsplit("/", 1)[-1]:
                raise HttpError(404, "Não encontrado")
            target = WEB_DIR / "index.html"
        req.file(target, guess_mime(str(target)))


# --------------------------------------------------------------------------- requisição
def _under(target: Path, root: Path) -> bool:
    """`target` está dentro de `root`? (comparação por pastas, não por prefixo de texto: «/x/web2» não está dentro de «/x/web».)"""
    root = Path(root).resolve()
    return target == root or root in target.parents



class Request:
    def __init__(self, handler: "Handler", method: str):
        self.h = handler
        self.method = method
        parsed = urllib.parse.urlsplit(handler.path)
        self.path = parsed.path
        self.query = urllib.parse.parse_qs(parsed.query)
        self.headers = handler.headers
        self.rfile = handler.rfile
        self._sse = False

    # entrada
    def content_length(self) -> int:
        if "chunked" in (self.headers.get("Transfer-Encoding") or "").lower():
            raise HttpError(411, "Envie o corpo com Content-Length (corpo em pedaços não é aceito)")   # v0.78: antes era lido como vazio, em silêncio
        raw = self.headers.get("Content-Length")
        if raw is None or str(raw).strip() == "":
            return 0
        try:
            n = int(str(raw).strip())
        except ValueError:
            raise HttpError(400, "Content-Length inválido") from None
        if n < 0:
            raise HttpError(400, "Content-Length inválido")   # v0.78: valor negativo ou ilegível virava «corpo vazio» e a requisição passava como válida
        return n

    def body_bytes(self, limit: int = 8 * 1024 * 1024) -> bytes:
        n = self.content_length()
        if n > limit:
            raise HttpError(413, "Corpo da requisição muito grande")
        self._body_read = True
        return self.rfile.read(n) if n else b""

    def body_json(self, limit: int = 8 * 1024 * 1024) -> Any:
        raw = self.body_bytes(limit)
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError, RecursionError):   # RecursionError: «[[[[…» com milhares de níveis
            raise HttpError(400, "JSON inválido")
        if not isinstance(data, dict):  # todas as rotas esperam um objeto: lista/texto/número virariam um erro 500 lá dentro
            raise HttpError(400, "JSON inválido: esperava um objeto {…}")
        try:
            return _clean_json(data)
        except ValueError:
            raise HttpError(400, "JSON inválido: aninhado fundo demais")

    # saída
    def _head(self, status: int, mime: str, length: Optional[int], extra: Optional[Dict[str, str]] = None) -> None:
        h = self.h
        h.send_response(status)
        headers = {"Content-Type": mime, "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"}
        if length is not None:
            headers["Content-Length"] = str(length)
        headers.update(extra or {})  # `extra` pode sobrescrever (ex.: Cache-Control de mídias imutáveis)
        for k, v in headers.items():
            h.send_header(k, v)
        h.end_headers()

    def json(self, obj: Any, status: int = 200) -> None:
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._head(status, "application/json; charset=utf-8", len(data))
        if self.method != "HEAD":
            self.h.wfile.write(data)

    def bytes(self, data: bytes, mime: str, status: int = 200, headers: Optional[Dict[str, str]] = None) -> None:
        self._head(status, mime, len(data), headers)
        if self.method != "HEAD":
            self.h.wfile.write(data)

    def file(self, path: Path, mime: str, download_name: str = "", cache: bool = False, headers: Optional[Dict[str, str]] = None) -> None:
        """Envia um arquivo, com suporte a `Range` (necessário p/ buscar em <video>/<audio>)."""
        size = path.stat().st_size
        extra = {"Accept-Ranges": "bytes"}
        if cache:  # arquivos com id único (nunca mudam)
            extra["Cache-Control"] = "private, max-age=3600"
        if download_name:
            extra["Content-Disposition"] = f'attachment; filename="{safe_filename(download_name)}"'
        extra.update(headers or {})
        status, start, end = 200, 0, size - 1
        rng = (self.headers.get("Range") or "").strip()
        m = re.match(r"^bytes=(\d*)-(\d*)$", rng)
        if m and size and (m.group(1) or m.group(2)):
            a, b = m.groups()
            if not a:  # sufixo: os últimos N bytes
                start, end = max(0, size - int(b)), size - 1
            else:
                start, end = int(a), min(int(b), size - 1) if b else size - 1
            if start > end or start >= size:
                self._head(416, "text/plain", 0, {"Content-Range": f"bytes */{size}"})
                return
            status = 206
            extra["Content-Range"] = f"bytes {start}-{end}/{size}"
        length = max(0, end - start + 1) if size else 0
        self._head(status, mime, length, extra)
        if self.method == "HEAD":
            return
        with open(path, "rb") as fh:
            fh.seek(start)
            left = length
            while left > 0:
                chunk = fh.read(min(1 << 20, left))
                if not chunk:
                    break
                self.h.wfile.write(chunk)
                left -= len(chunk)

    def static(self, root: Path, rel: str) -> None:
        if "\x00" in rel:
            raise HttpError(404, "Arquivo não encontrado")
        target = (root / rel).resolve()
        if not _under(target, root) or not target.is_file():
            raise HttpError(404, "Arquivo não encontrado")
        self.file(target, guess_mime(rel))

    def redirect(self, url: str) -> None:
        self._head(302, "text/plain", 0, {"Location": url})

    def sse_start(self) -> None:
        if not getattr(self, "_body_read", False):  # corpo não lido (ex.: «regenerar» manda {}): fechar o socket com dados pendentes dá RST (macOS) e corta a resposta
            try:
                n = self.content_length()
                if 0 < n <= 1024 * 1024:
                    self._body_read = True
                    self.rfile.read(n)
            except (HttpError, OSError, ValueError):
                pass
        self._sse = True
        self.h.send_response(200)
        self.h.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.h.send_header("Cache-Control", "no-cache, no-transform")
        self.h.send_header("X-Accel-Buffering", "no")
        self.h.send_header("Connection", "close")
        self.h.end_headers()
        self.h.wfile.flush()

    def sse_send(self, obj: Any, event_id: Optional[int] = None) -> None:
        head = b"id: %d\n" % event_id if isinstance(event_id, int) else b""   # com `id`, a reconexão automática do navegador continua de onde parou
        self.h.wfile.write(head + b"data: " + json.dumps(obj, ensure_ascii=False).encode("utf-8") + b"\n\n")
        self.h.wfile.flush()

    def sse_comment(self, text_: str) -> None:
        self.h.wfile.write(f": {text_}\n\n".encode("utf-8"))
        self.h.wfile.flush()


class Handler(BaseHTTPRequestHandler):
    app: App
    server_version = "ScribeFlow/" + __version__
    sys_version = ""

    def log_message(self, fmt: str, *args: Any) -> None:  # silencioso; erros vão para stderr via handler
        pass

    def _handle(self, method: str) -> None:
        req = Request(self, method)
        try:
            if not self.app.host_allowed(self.headers.get("Host", "")):
                raise HttpError(403, "Host não permitido")
            if method in ("POST", "PUT", "DELETE"):
                origin = self.headers.get("Origin")
                if origin:
                    if urllib.parse.urlsplit(origin).netloc != self.headers.get("Host", ""):
                        raise HttpError(403, "Origem não permitida")
            path = req.path
            if path.startswith("/api/"):
                if not self.app.dispatch(req):
                    raise HttpError(404, "Rota não encontrada")
            elif method in ("GET", "HEAD"):
                self.app.serve_static(req)
            else:
                raise HttpError(405, "Método não permitido")
        except HttpError as exc:
            if req._sse:
                return
            payload: Any = {"error": exc.message}
            if exc.status == 409:
                try:
                    payload.update(json.loads(exc.message))
                except ValueError:
                    pass
            req.json(payload, exc.status)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            if not req._sse:
                try:
                    req.json({"error": f"Erro interno: {exc}"}, 500)
                except OSError:
                    pass

    def do_GET(self) -> None:
        self._handle("GET")

    def do_HEAD(self) -> None:
        self._handle("HEAD")

    def do_POST(self) -> None:
        self._handle("POST")

    def do_PUT(self) -> None:
        self._handle("PUT")

    def do_DELETE(self) -> None:
        self._handle("DELETE")


def exclusive_port(sock: Any, windows: Optional[bool] = None) -> bool:
    """Porta só deste processo (v0.60). No Windows o `SO_REUSEADDR` deixa DOIS programas abrirem a mesma porta sem erro (diferente do Linux/macOS): abrir o `flow` duas vezes não passava para a porta seguinte
    (8788…) — as duas janelas disputavam a 8787 e o navegador caía numa ou noutra. Lá usa-se `SO_EXCLUSIVEADDRUSE` (a segunda tentativa dá erro, e o laço de portas do ScribeFlow segue para a próxima). True se aplicou."""
    if not (os.name == "nt" if windows is None else windows):
        return False
    opt = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
    if opt is None:
        return False
    try:
        sock.setsockopt(socket.SOL_SOCKET, opt, 1)
    except OSError:
        return False
    return True


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = os.name != "nt"   # Windows: SO_REUSEADDR deixa duas instâncias na mesma porta (ver `exclusive_port`)
    request_queue_size = 64
    app: Optional["App"] = None

    def server_bind(self) -> None:
        exclusive_port(self.socket)
        super().server_bind()

def make_server(host: str, port: int, store: Optional[Store] = None) -> Tuple[Server, App]:
    store = store or Store()
    app = App(store, host)

    class BoundHandler(Handler):
        pass

    BoundHandler.app = app
    httpd = Server((host, port), BoundHandler)
    httpd.app = app
    return httpd, app
