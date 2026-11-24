"""Projetos do ScribeFlow em disco — o mesmo sistema do OpenFlow (uma pasta por projeto, JSON aberto, pesquisa, duplicar, apagar, exportar e importar), com um texto por projeto.

    projects/<id>/project.json     nome, descrição, tipo de escrita, idioma, formatação e o **system prompt geral** que guia a IA
    projects/<id>/document.json    o documento: blocos (ver docmodel.py) — formato aberto, legível, sem banco de dados
    projects/<id>/sources.json     fontes da web guardadas pela pessoa para citar
    projects/<id>/history/         pontos de retorno do documento (antes de cada mudança grande)
    projects/<id>/exports/         .docx, .md, .txt e .html gerados

Um projeto também sai e entra como um único arquivo **JSON** (`export_json` / `import_json`). Texto vindo da tela, da IA ou de arquivos importados é entrada não confiável:
`docmodel` e `docx` validam tudo, e o JSON importado passa pelas mesmas normalizações de qualquer outro caminho (nunca sobrescreve um projeto existente: sempre cria um novo).
"""
from __future__ import annotations

import html
import json
import re
import shutil
import threading
import time
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import __version__, docmodel as D, docx as X, schema as S
from .util import new_id, now_iso, read_json, safe_filename, slugify, text, write_json

MAX_PROJECTS = 500
MAX_IMPORT = 48 * 1024 * 1024
MAX_EXPORTS = 60
HISTORY_KEEP = 40
MAX_SYSTEM_PROMPT = 12000
EXPORT_FORMATS = ("docx", "md", "txt", "html")
JSON_FORMAT = "scribeflow.project"
JSON_VERSION = 1
_ID_RE = re.compile(r"^[a-z0-9_-]{3,60}$")


class ProjectError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def valid_id(pid: Any) -> bool:
    return isinstance(pid, str) and _ID_RE.match(pid) is not None


def _fold(s: Any) -> str:
    """Minúsculas e sem acentos: «Cenário» e «cenario» são a mesma palavra na pesquisa."""
    return "".join(ch for ch in unicodedata.normalize("NFKD", str(s or "")) if not unicodedata.combining(ch)).lower()


def _plain_blocks(s: str) -> List[Dict[str, Any]]:
    """Texto puro: cada linha não vazia é um parágrafo (sem interpretar Markdown)."""
    return [D.block("p", [D.run(ln.strip())]) for ln in s.replace("\r\n", "\n").split("\n") if ln.strip()][: D.MAX_BLOCKS]


class ProjectStore:
    def __init__(self, folder: Path, store: Any = None):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.store = store
        self.lock = threading.RLock()

    # ------------------------------------------------------------------ caminhos
    def dir(self, pid: str) -> Path:
        if not valid_id(pid):
            raise ProjectError(404, "Projeto não encontrado.")
        d = self.folder / pid
        if not (d / "project.json").is_file():
            raise ProjectError(404, "Projeto não encontrado.")
        return d

    # ------------------------------------------------------------------ metadados
    def _norm_meta(self, m: Dict[str, Any]) -> Dict[str, Any]:
        t = m.get("type") if isinstance(m.get("type"), str) and m.get("type") in S.WRITING_TYPES else S.DEFAULT_TYPE
        try:
            wpp = int(max(50, min(1000, float(m.get("words_per_page")))))
        except (TypeError, ValueError):
            wpp = S.WRITING_TYPES[t]["wpp"]
        return {"id": m.get("id", ""), "name": text(m.get("name"), "Sem título", 100), "type": t, "language": S.norm_lang(m.get("language")),
                "content": m.get("content") if m.get("content") in ("sfw", "free") else "", "format": S.norm_format(m.get("format"), S.WRITING_TYPES[t]["preset"]),
                "system_prompt": str(m.get("system_prompt") or "")[:MAX_SYSTEM_PROMPT], "words_per_page": wpp,
                "ignore": [text(w, "", 60) for w in (m.get("ignore") if isinstance(m.get("ignore"), list) else []) if isinstance(w, str)][:500], "author": text(m.get("author"), "", 80),
                "description": text(m.get("description"), "", 400), "created": str(m.get("created") or ""), "updated": str(m.get("updated") or ""),
                "words": int(m.get("words") or 0), "excerpt": text(m.get("excerpt"), "", 220)}

    def meta(self, pid: str) -> Dict[str, Any]:
        m = read_json(self.dir(pid) / "project.json")
        if not isinstance(m, dict):
            raise ProjectError(500, "project.json ilegível.")
        n = self._norm_meta(m)
        n["id"] = pid
        return n

    def _write_meta(self, pid: str, meta: Dict[str, Any]) -> Dict[str, Any]:
        meta = dict(meta)
        meta["id"] = pid
        meta["updated"] = now_iso()
        write_json(self.folder / pid / "project.json", meta)
        return meta

    def summary(self, n: Dict[str, Any]) -> Dict[str, Any]:
        return {"id": n["id"], "name": n["name"], "description": n["description"], "type": n["type"], "language": n["language"], "created": n["created"], "updated": n["updated"],
                "words": n["words"], "pages": S.pages_for(n["words"], n["words_per_page"]), "excerpt": n["excerpt"], "has_system_prompt": bool(n["system_prompt"].strip())}

    def list(self, q: str = "", sort: str = "updated") -> List[Dict[str, Any]]:
        """Resumo de todos os projetos. `q` pesquisa (sem diferenciar acentos nem maiúsculas; todas as palavras precisam aparecer) no nome, na descrição, no system prompt e no texto;
        cada resultado diz onde achou em `match`. `sort`: updated (padrão, mais recentes primeiro), created, name ou words."""
        tokens = [t for t in _fold(q).split() if t]
        out = []
        for d in self.folder.iterdir():
            if not (d.is_dir() and valid_id(d.name) and (d / "project.json").is_file()):
                continue
            try:
                n = self.meta(d.name)
            except ProjectError:
                continue
            row = self.summary(n)
            if tokens:
                where = self._match(n, tokens)
                if where is None:
                    continue
                row["match"] = where
            out.append(row)
        if sort == "name":
            out.sort(key=lambda c: _fold(c["name"]))
        elif sort == "created":
            out.sort(key=lambda c: c.get("created", ""))
        elif sort == "words":
            out.sort(key=lambda c: (-c["words"], _fold(c["name"])))
        else:
            out.sort(key=lambda c: c.get("updated", ""), reverse=True)
        return out

    def _match(self, n: Dict[str, Any], tokens: List[str]) -> Optional[str]:
        """Onde o projeto casa com a pesquisa: "" (no nome), «descrição», «system prompt» ou o trecho do texto. None se alguma palavra não aparece em lugar nenhum."""
        fields = [("", n["name"]), ("descrição", n["description"]), ("system prompt", n["system_prompt"])]
        try:
            for b in D.norm_blocks((read_json(self.folder / n["id"] / "document.json") or {}).get("blocks")):
                if b.get("t") in D.TEXT_TYPES:
                    t = D.text_of(b)
                    if t.strip():
                        fields.append((t.strip().replace("\n", " ")[:80], t))
        except OSError:
            pass
        hay = [(where, _fold(t)) for where, t in fields if t]
        blob = " ".join(h for _w, h in hay)
        if not all(t in blob for t in tokens):
            return None
        for where, h in hay:   # o primeiro campo que tem a primeira palavra diz «onde»
            if tokens[0] in h:
                return where
        return ""

    def create(self, name: str = "", type_id: str = S.DEFAULT_TYPE, language: str = "", description: str = "", content: str = "", fmt: Any = None, system_prompt: str = "") -> Dict[str, Any]:
        with self.lock:
            if sum(1 for _ in self.folder.iterdir()) >= MAX_PROJECTS:
                raise ProjectError(400, f"Limite de {MAX_PROJECTS} projetos. Apague algum para criar outro.")
            t = type_id if isinstance(type_id, str) and type_id in S.WRITING_TYPES else S.DEFAULT_TYPE
            name = text(name, "", 100) or {"pt": "Novo texto", "en": "New text"}.get(S.lang_base(language or S.DEFAULT_LANG), "Novo texto")
            pid = (slugify(name, "texto", 24) + "-" + new_id()[:6]).lower()
            d = self.folder / pid
            for sub in ("history", "exports"):
                (d / sub).mkdir(parents=True, exist_ok=True)
            meta = {"id": pid, "name": name, "type": t, "language": S.norm_lang(language), "content": content if content in ("sfw", "free") else "",
                    "format": S.norm_format(fmt, S.WRITING_TYPES[t]["preset"]), "system_prompt": str(system_prompt or "")[:MAX_SYSTEM_PROMPT], "words_per_page": S.WRITING_TYPES[t]["wpp"],
                    "ignore": [], "description": text(description, "", 400), "created": now_iso(), "words": 0, "excerpt": ""}
            self._write_meta(pid, meta)
            write_json(d / "document.json", {"v": 1, "blocks": []})
            return self.meta(pid)

    def update_meta(self, pid: str, patch: Any) -> Dict[str, Any]:
        p = patch if isinstance(patch, dict) else {}
        with self.lock:
            m = read_json(self.dir(pid) / "project.json") or {}
            if isinstance(p.get("name"), str) and p["name"].strip():
                m["name"] = text(p["name"], m.get("name", ""), 100)
            if isinstance(p.get("type"), str) and p["type"] in S.WRITING_TYPES:
                m["type"] = p["type"]
            if isinstance(p.get("language"), str):
                m["language"] = S.norm_lang(p["language"])
            if p.get("content") in ("", "sfw", "free"):
                m["content"] = p["content"]
            if isinstance(p.get("format"), dict):
                m["format"] = S.norm_format({**(m.get("format") if isinstance(m.get("format"), dict) else {}), **p["format"]}, S.WRITING_TYPES.get(m.get("type"), S.WRITING_TYPES[S.DEFAULT_TYPE])["preset"])
            if isinstance(p.get("description"), str):
                m["description"] = text(p["description"], "", 400)
            if isinstance(p.get("author"), str):
                m["author"] = text(p["author"], "", 80)
            if isinstance(p.get("system_prompt"), str):
                m["system_prompt"] = p["system_prompt"][:MAX_SYSTEM_PROMPT]
            if isinstance(p.get("words_per_page"), (int, float)) and not isinstance(p.get("words_per_page"), bool):
                m["words_per_page"] = int(max(50, min(1000, p["words_per_page"])))
            if isinstance(p.get("ignore"), list):
                m["ignore"] = [text(w, "", 60) for w in p["ignore"] if isinstance(w, str) and w.strip()][:500]
            self._write_meta(pid, m)
            return self.meta(pid)

    def delete(self, pid: str) -> None:
        with self.lock:
            shutil.rmtree(self.dir(pid))

    def duplicate(self, pid: str, name: str = "") -> Dict[str, Any]:
        with self.lock:
            src = self.meta(pid)
            n = self.create(name or (src["name"] + " (cópia)"), src["type"], src["language"], src["description"], src["content"], src["format"], src["system_prompt"])
            self.save_doc(n["id"], blocks=self.get_doc(pid)["blocks"], snapshot=False)
            self.update_meta(n["id"], {"ignore": src["ignore"], "author": src["author"], "words_per_page": src["words_per_page"]})
            self.save_sources(n["id"], self.get_sources(pid))
            return self.meta(n["id"])

    # ------------------------------------------------------------------ documento
    def get_doc(self, pid: str) -> Dict[str, Any]:
        d = read_json(self.dir(pid) / "document.json")
        blocks = D.norm_blocks(d.get("blocks") if isinstance(d, dict) else [])
        return {"blocks": blocks, "html": D.blocks_to_html(blocks), "stats": D.stats(blocks), "updated": self.meta(pid).get("updated", "")}

    def save_doc(self, pid: str, blocks: Any = None, html_src: Optional[str] = None, markdown: Optional[str] = None, snapshot: bool = True, label: str = "") -> Dict[str, Any]:
        """Grava o documento (de blocos, HTML do editor ou Markdown). `snapshot` guarda o anterior no histórico (se mudou)."""
        if blocks is None:
            blocks = D.html_to_blocks(html_src) if html_src is not None else D.markdown_to_blocks(markdown or "") if markdown is not None else []
        nb = D.norm_blocks(blocks)
        with self.lock:
            d = self.dir(pid)
            if snapshot:
                cur = D.norm_blocks((read_json(d / "document.json") or {}).get("blocks"))
                if cur and cur != nb and label:
                    self._snapshot_blocks(pid, cur, label)
            write_json(d / "document.json", {"v": 1, "blocks": nb})
            m = read_json(d / "project.json") or {}
            m["words"] = D.stats(nb)["words"]
            m["excerpt"] = re.sub(r"\s+", " ", D.blocks_to_text(nb)[:600]).strip()[:220]
            self._write_meta(pid, m)
        return {"stats": D.stats(nb), "updated": self.meta(pid)["updated"]}

    # ------------------------------------------------------------------ histórico (desfazer mudanças grandes)
    def _snapshot_blocks(self, pid: str, blocks: List[Dict[str, Any]], label: str) -> str:
        hid = time.strftime("%Y%m%d-%H%M%S") + "-" + new_id()[:4]
        write_json(self.folder / pid / "history" / (hid + ".json"), {"v": 1, "id": hid, "label": text(label, "", 100), "t": now_iso(), "words": D.stats(blocks)["words"], "blocks": blocks})
        keep = 25
        if self.store is not None:
            try:
                keep = int(max(5, min(100, self.store.get_settings()["scriber"]["undo_keep"])))
            except (KeyError, TypeError, ValueError):
                pass
        files = sorted((self.folder / pid / "history").glob("*.json"))
        for f in files[: max(0, len(files) - keep)]:
            f.unlink(missing_ok=True)
        return hid

    def snapshot(self, pid: str, label: str = "manual") -> str:
        with self.lock:
            self.dir(pid)
            return self._snapshot_blocks(pid, self.get_doc(pid)["blocks"], label)

    def history(self, pid: str) -> List[Dict[str, Any]]:
        out = []
        for f in sorted(self.dir(pid).joinpath("history").glob("*.json"), reverse=True):
            d = read_json(f)
            if isinstance(d, dict):
                out.append({"id": d.get("id", f.stem), "label": d.get("label", ""), "t": d.get("t", ""), "words": d.get("words", 0)})
        return out[:HISTORY_KEEP * 3]

    def restore(self, pid: str, hid: str) -> Dict[str, Any]:
        if not re.match(r"^[\w-]{6,40}$", hid or ""):
            raise ProjectError(404, "Ponto de retorno não encontrado.")
        with self.lock:
            f = self.dir(pid) / "history" / (hid + ".json")
            d = read_json(f) if f.is_file() else None
            if not isinstance(d, dict):
                raise ProjectError(404, "Ponto de retorno não encontrado.")
            self._snapshot_blocks(pid, self.get_doc(pid)["blocks"], "antes de voltar a " + text(d.get("label"), "", 40))
            return self.save_doc(pid, blocks=d.get("blocks"), snapshot=False)

    # ------------------------------------------------------------------ fontes da web guardadas
    @staticmethod
    def _norm_sources(sources: Any) -> List[Dict[str, Any]]:
        out = []
        for s in sources if isinstance(sources, list) else []:
            if isinstance(s, dict) and isinstance(s.get("url"), str) and s["url"].startswith(("http://", "https://")):
                out.append({"title": text(s.get("title"), "", 200), "url": text(s.get("url"), "", 600), "note": text(s.get("note"), "", 800), "text": text(s.get("text"), "", 6000), "pinned": bool(s.get("pinned"))})
        return out[:60]

    def get_sources(self, pid: str) -> List[Dict[str, Any]]:
        d = read_json(self.dir(pid) / "sources.json")
        return self._norm_sources(d.get("sources") if isinstance(d, dict) else [])

    def save_sources(self, pid: str, sources: Any) -> List[Dict[str, Any]]:
        ns = self._norm_sources(sources)
        with self.lock:
            write_json(self.dir(pid) / "sources.json", {"v": 1, "sources": ns})
        return ns

    # ------------------------------------------------------------------ exportar / importar o texto (.docx, .md, .txt, .html)
    def render(self, pid: str, fmt: str) -> bytes:
        if fmt not in EXPORT_FORMATS:
            raise ProjectError(400, "Formato inválido: " + ", ".join(EXPORT_FORMATS))
        m = self.meta(pid)
        blocks = self.get_doc(pid)["blocks"]
        if fmt == "docx":
            return X.build_docx(blocks, {"title": m["name"], "author": m["author"] or m["format"]["author"]}, m["format"], m["language"])
        if fmt == "md":
            return D.blocks_to_markdown(blocks).encode("utf-8")
        if fmt == "txt":
            return D.blocks_to_text(blocks).replace("\f", "\n\n").encode("utf-8")
        f = m["format"]
        css = (f"body{{font-family:'{f['font']}',serif;font-size:{f['size']}pt;line-height:{f['line']};max-width:42em;margin:2em auto;padding:0 1em}}p{{margin:0 0 {f['space_after']}pt;text-indent:{f['indent']}cm;text-align:{f['align']}}}"
               "h1,h2,h3{text-indent:0}blockquote{margin:1em 2em;font-style:italic}.pb{break-after:page}")
        doc = f'<!doctype html><html lang="{m["language"]}"><head><meta charset="utf-8"><title>{html.escape(m["name"])}</title><style>{css}</style></head><body>{D.blocks_to_html(blocks)}</body></html>'
        return doc.encode("utf-8")

    def export(self, pid: str, fmt: str) -> Dict[str, Any]:
        data = self.render(pid, fmt)
        with self.lock:
            m = self.meta(pid)
            name = f"{slugify(m['name'], 'texto', 40)}-{time.strftime('%Y%m%d-%H%M%S')}.{fmt}"
            ed = self.dir(pid) / "exports"
            ed.mkdir(exist_ok=True)
            (ed / name).write_bytes(data)
            files = sorted(ed.iterdir(), key=lambda p: p.stat().st_mtime)
            for f in files[: max(0, len(files) - MAX_EXPORTS)]:
                f.unlink(missing_ok=True)
        return {"name": name, "size": len(data), "format": fmt}

    def list_exports(self, pid: str) -> List[Dict[str, Any]]:
        ed = self.dir(pid) / "exports"
        out = [{"name": p.name, "size": p.stat().st_size, "t": p.stat().st_mtime} for p in ed.iterdir() if p.is_file()] if ed.is_dir() else []
        out.sort(key=lambda x: -x["t"])
        return out

    def export_path(self, pid: str, name: str) -> Path:
        name = safe_filename(name)
        p = self.dir(pid) / "exports" / name
        if not p.is_file() or p.parent != (self.dir(pid) / "exports"):
            raise ProjectError(404, "Arquivo não encontrado.")
        return p

    def delete_export(self, pid: str, name: str) -> None:
        self.export_path(pid, name).unlink(missing_ok=True)

    def import_file(self, pid: str, filename: str, data: bytes, mode: str = "replace") -> Dict[str, Any]:
        """Importa .docx, .md, .txt ou .html para o texto do projeto: `replace` (guarda o anterior no histórico) ou `append`."""
        if len(data) > MAX_IMPORT:
            raise ProjectError(413, "Arquivo grande demais para importar.")
        ext = Path(str(filename or "")).suffix.lower()
        meta: Dict[str, Any] = {}
        if ext == ".docx" or data[:2] == b"PK":
            try:
                blocks, meta = X.parse_docx(data)
            except X.DocxError as exc:
                raise ProjectError(400, str(exc)) from None
        else:
            try:
                s = data.decode("utf-8-sig")
            except UnicodeDecodeError:
                s = data.decode("latin-1")
            if ext in (".html", ".htm"):
                blocks = D.html_to_blocks(s)
            elif ext in (".md", ".markdown"):
                blocks = D.markdown_to_blocks(s)
            else:
                blocks = _plain_blocks(s)
        if not blocks:
            raise ProjectError(400, "Não achei texto nesse arquivo.")
        with self.lock:
            cur = self.get_doc(pid)["blocks"]
            nb = (cur + blocks) if mode == "append" else blocks
            if cur:
                self._snapshot_blocks(pid, cur, "antes de importar " + text(filename, "arquivo", 40))
            self.save_doc(pid, blocks=nb, snapshot=False)
            patch: Dict[str, Any] = {}
            if meta.get("language") and mode != "append":
                patch["language"] = meta["language"]
            if meta.get("author") and not self.meta(pid)["author"]:
                patch["author"] = meta["author"]
            if patch:
                self.update_meta(pid, patch)
        return {"stats": D.stats(nb), "added": len(blocks), "meta": meta}

    # ------------------------------------------------------------------ exportar / importar o PROJETO inteiro como JSON
    def export_json(self, pid: str, history: bool = True) -> Dict[str, Any]:
        """O projeto inteiro em um objeto JSON: dados, system prompt geral, formatação, documento (blocos), fontes e (opcional) o histórico. Nunca inclui configurações nem tokens."""
        m = self.meta(pid)
        hist: List[Dict[str, Any]] = []
        if history:
            for f in sorted((self.dir(pid) / "history").glob("*.json"))[-HISTORY_KEEP:]:
                d = read_json(f)
                if isinstance(d, dict) and isinstance(d.get("blocks"), list):
                    hist.append({"label": text(d.get("label"), "", 100), "t": str(d.get("t") or ""), "blocks": D.norm_blocks(d["blocks"])})
        return {"format": JSON_FORMAT, "version": JSON_VERSION, "app": "ScribeFlow " + __version__, "exported": now_iso(),
                "project": {k: m[k] for k in ("name", "description", "type", "language", "content", "format", "system_prompt", "author", "words_per_page", "ignore", "created")},
                "document": {"blocks": self.get_doc(pid)["blocks"]}, "sources": self.get_sources(pid), "history": hist}

    def import_json(self, payload: Any) -> Dict[str, Any]:
        """Cria um projeto NOVO a partir de um JSON exportado pelo ScribeFlow. Tudo é revalidado (tipos, tamanhos, blocos): o arquivo é tratado como não confiável."""
        if not isinstance(payload, dict) or payload.get("format") != JSON_FORMAT or not isinstance(payload.get("project"), dict):
            raise ProjectError(400, "Este arquivo não é um projeto do ScribeFlow (esperava um JSON exportado por ele).")
        v = payload.get("version")
        if not isinstance(v, int) or isinstance(v, bool) or v < 1 or v > JSON_VERSION:
            raise ProjectError(400, "Versão do arquivo não suportada (atualize o ScribeFlow).")
        p = payload["project"]
        doc = payload.get("document") if isinstance(payload.get("document"), dict) else {}
        blocks = D.norm_blocks(doc.get("blocks"))
        with self.lock:
            meta = self.create(text(p.get("name"), "", 100), p.get("type") if isinstance(p.get("type"), str) else S.DEFAULT_TYPE, p.get("language") if isinstance(p.get("language"), str) else "",
                               text(p.get("description"), "", 400), p.get("content") if isinstance(p.get("content"), str) else "", p.get("format"), str(p.get("system_prompt") or ""))
            pid = meta["id"]
            self.update_meta(pid, {"author": p.get("author") if isinstance(p.get("author"), str) else "", "ignore": p.get("ignore") if isinstance(p.get("ignore"), list) else [],
                                   "words_per_page": p.get("words_per_page")})
            self.save_doc(pid, blocks=blocks, snapshot=False)
            self.save_sources(pid, payload.get("sources"))
            for h in (payload.get("history") if isinstance(payload.get("history"), list) else [])[-HISTORY_KEEP:]:
                if isinstance(h, dict) and isinstance(h.get("blocks"), list):
                    self._snapshot_blocks(pid, D.norm_blocks(h["blocks"]), text(h.get("label"), "histórico importado", 100))
            return self.meta(pid)


def json_bytes(obj: Any) -> bytes:
    return json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
