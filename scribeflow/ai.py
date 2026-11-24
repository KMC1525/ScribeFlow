"""A IA do ScribeFlow: o **Editor** (melhorar, expandir, reescrever, encurtar, corrigir, continuar, diálogo, descrever, tom, traduzir, pedir…) e o **Revisor ortográfico**.

Tudo roda no modelo de texto local (ver `llm.py`). O **system prompt geral** do projeto — a caixa de texto que substituiu os lorebooks — entra em TODAS as chamadas como a «lei» do texto:
estilo, voz, personagens, mundo, regras e o que a IA deve lembrar. A IA escreve **texto** (o Revisor, um JSON validado); nada que ela devolva é executado, e o que entra no documento
passa pelo modelo de blocos (`docmodel`) como qualquer outro texto. Sem modelo ou sem motor, as ações que dá para fazer com regras (corrigir, encurtar) ainda funcionam.
"""
from __future__ import annotations

import json
import re
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import docmodel as D, schema as S, spell
from .jobs import Job
from .llm import ContextTooLong, LocalLLM, fit_budget
from .net import ProviderError
from .util import Cancelled, clamp, strip_reasoning, text

PROMPTS = Path(__file__).parent / "prompts"
POLICY_FREE = ("Content policy: ScribeFlow adds no content filters of its own. This is a private creative workspace for adults. Follow the author's request, tone and worldbuilding faithfully; "
               "mature, dark, violent and adult (NSFW) themes are allowed when the author or the story calls for them; do not moralize, lecture or sanitize. "
               "One fixed rule: any sexual content must involve only adult characters (18+).")
POLICY_SFW = "Content policy: keep everything suitable for all audiences (SFW): no explicit sexual content or gratuitous gore."
POLICY_FIXED = " Never write sexual content about real, identifiable people."
CHARS_PER_TOKEN = 3


@lru_cache(maxsize=16)
def prompt(name: str) -> str:
    try:
        return (PROMPTS / f"{name}.md").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def system_message(role: str, meta: Dict[str, Any], content: str, web_notes: str = "") -> str:
    """O system prompt de cada chamada: regras do ScribeFlow + papel + política de conteúdo + **o system prompt geral do projeto** + tipo do documento."""
    t = S.WRITING_TYPES[meta["type"]]
    parts = [prompt("core"), prompt(role), (POLICY_SFW if content == "sfw" else POLICY_FREE) + POLICY_FIXED,
             f"DOCUMENT TYPE: {t['label']}. {t['guide']}"]
    sp = (meta.get("system_prompt") or "").strip()
    if sp:
        parts.append("AUTHOR'S GENERAL SYSTEM PROMPT (canon; follow it in every action):\n" + sp)
    if web_notes:
        parts.append("WEB NOTES (numbered sources):\n" + web_notes)
    return "\n\n".join(p for p in parts if p)


class ScribeAI:
    """Uma execução da IA (uma ação do editor ou uma revisão): guarda o modelo, o job e emite eventos para a tela."""

    def __init__(self, store: Any, mgr: Any, llm: LocalLLM, opts: Dict[str, Any], job: Optional[Job]):
        self.store, self.mgr, self.llm, self.opts, self.job = store, mgr, llm, opts or {}, job
        self.settings = store.get_settings()
        self.cfg = self.settings["scriber"]
        self.content = self.opts.get("content") or self.cfg["content"] or "free"
        self.warnings: List[str] = []
        self.sources: List[Dict[str, Any]] = []
        self.live = True
        self.error = ""
        try:
            from .llm import llama_available, resolve_model

            if resolve_model(store, self.settings) is None:
                self.live, self.error = False, "Nenhum modelo de texto baixado: usei só as regras do ScribeFlow. Baixe um em Configurações → Modelo de texto (IA)."
            elif not llama_available()["installed"]:
                self.live, self.error = False, "O motor de IA local não está instalado: usei só as regras. Rode no terminal:  scribeflow engine install"
        except Exception as exc:  # noqa: BLE001
            self.live, self.error = False, str(exc)[:200]

    # ------------------------------------------------------------------ infraestrutura
    def emit(self, ev: Dict[str, Any]) -> None:
        if self.job is not None:
            self.job.emit(ev)

    def check(self) -> None:
        if self.job is not None and self.job.cancelled:
            raise Cancelled()

    def cancelled(self) -> bool:
        return bool(self.job is not None and self.job.cancelled)

    def _ask(self, system: str, user: str, max_tokens: int, temperature: float, json_schema: Optional[dict] = None, progress: bool = False) -> str:
        """Uma chamada ao modelo local. Com `progress`, manda para a tela quantas palavras já saíram."""
        last = [0.0]

        def partial(txt: str) -> None:
            if time.time() - last[0] > 0.4:
                last[0] = time.time()
                self.emit({"type": "partial", "words": S.count_words(txt)})

        out, stop = self.llm.generate([{"role": "system", "content": system}, {"role": "user", "content": user}], max_tokens=max_tokens, temperature=temperature,
                                      on_text=partial if progress else None, cancelled=self.cancelled, json_schema=json_schema)
        if stop == "length" and not json_schema:
            self.warnings.append("A resposta foi cortada no limite de tamanho: aumente a janela de contexto ou peça um trecho menor.")
        return out

    def done(self, result: Dict[str, Any]) -> Dict[str, Any]:
        result = dict(result)
        result["ai"] = self.live
        result["warning"] = "" if self.live else self.error
        result["warnings"] = self.warnings[:10]
        self.emit({"type": "result", "data": result})
        return result

    def web_context(self, prompt_text: str) -> str:
        """Busca na web nativa (DuckDuckGo/Wikipédia) + as fontes que a pessoa fixou; vira o bloco numerado de WEB NOTES."""
        web = text(self.opts.get("sources_text"), "", 12000)
        if self.opts.get("web") and prompt_text:
            self.emit({"type": "step", "id": "web", "label": "Busca na web", "status": "running"})
            try:
                from . import websearch

                found = websearch.gather(websearch.heuristic_query(prompt_text) or prompt_text[:200], self.settings, ui_lang=(self.settings.get("language") or "auto"))
                web = (web + "\n\n" + found.get("text", ""))[:14000].strip()
                self.sources = websearch.public_sources(found.get("sources", []))
                self.emit({"type": "sources", "sources": self.sources})
                self.emit({"type": "step", "id": "web", "label": "Busca na web", "status": "done", "note": f"{len(found.get('sources', []))} fonte(s)"})
            except Exception as exc:  # noqa: BLE001
                self.warnings.append("busca na web: " + str(exc)[:120])
                self.emit({"type": "step", "id": "web", "label": "Busca na web", "status": "warn", "note": str(exc)[:120]})
        return web

    # ================================================================ EDIÇÃO: trecho selecionado
    def edit_text(self, pid: str) -> Dict[str, Any]:
        meta = self.mgr.meta(pid)
        b = self.opts.get("body") or {}
        action = b.get("action") if isinstance(b.get("action"), str) and b.get("action") in S.ACTION_IDS else ("improve" if b.get("selection") else "continue")
        selection = text(b.get("selection"), "", 24000).replace("\xa0", " ")
        instruction = text(self.opts.get("prompt"), "", 3000)
        before, after = text(b.get("context_before"), "", 2500), text(b.get("context_after"), "", 1500)
        kind = b.get("kind") if b.get("kind") in S.SELECTION_KINDS else "paragraph"
        sel_words = S.count_words(selection)
        ex = S.norm_expand(b.get("expand"))
        lang = S.norm_lang(b.get("language") or meta["language"])
        if action in ("expand", "describe"):
            want = ex["words"] if ex["mode"] == "total" else sel_words + ex["words"]
        elif action == "continue":
            want = ex["words"]
        elif action == "shorten":
            want = ex["words"] if ex["mode"] == "total" and ex["words"] < sel_words else max(10, int(sel_words * 0.55))
        else:
            want = sel_words
        want = int(clamp(want, 5, 6000))
        self.emit({"type": "start", "steps": [{"id": "write", "label": "Editor"}], "ai": self.live, "warning": "" if self.live else self.error})
        out: Optional[str] = None
        note = ""
        if self.live:
            self.emit({"type": "step", "id": "write", "label": "Editor", "status": "running"})
            try:
                out = self._edit_ai(meta, action, selection, kind, instruction, before, after, want, sel_words, lang)
            except (Cancelled, ContextTooLong):
                raise
            except ProviderError as exc:
                if str(exc) == "cancelado":
                    raise Cancelled() from None
                raise
        if out is None:
            rules = self._edit_rules(action, selection, want, lang, meta)
            out, note = rules["text"], " ".join(rules["notes"])
            changed = rules["changed"]
        else:
            changed = True
        norm = out.strip()
        self.emit({"type": "step", "id": "write", "label": "Editor", "status": "done" if self.live else "warn", "note": note})
        return self.done({"text": norm, "paragraphs": [x for x in norm.split("\n") if x.strip()], "notes": [note] if note else [], "action": action, "changed": bool(changed and norm != selection.strip()),
                          "words": S.count_words(norm), "from_words": sel_words, "target_words": want, "sources": self.sources, "system_prompt_used": bool((meta.get("system_prompt") or "").strip())})

    def _edit_ai(self, meta: Dict[str, Any], action: str, selection: str, kind: str, instruction: str, before: str, after: str, want: int, sel_words: int, lang: str) -> str:
        web = self.web_context(instruction or selection[:300]) if (self.opts.get("web") or self.opts.get("sources_text")) else ""
        system = system_message("editor", meta, self.content, web)
        n_ctx = int(self.settings["model"]["n_ctx"])
        max_new = int(clamp(want * 2.4 + 300, 600, 8000))
        max_new = min(max_new, max(256, n_ctx // 2))   # a janela é do usuário: a resposta nunca come mais da metade dela
        # o contexto ao redor só entra se sobrar espaço depois do sistema e do trecho (a janela é limitada)
        spare_tokens = fit_budget(n_ctx, max_new) - self.llm.count_tokens(system) - self.llm.count_tokens(selection) - self.llm.count_tokens(instruction) - 200
        spare = max(0, spare_tokens) * CHARS_PER_TOKEN
        b_txt, a_txt = before[-min(len(before), int(spare * 0.65)):] if spare else "", after[:min(len(after), int(spare * 0.35))] if spare else ""
        lo, hi = int(want * 0.85), int(want * 1.25) + 5

        def user_msg(draft: Optional[str] = None, fix_note: str = "") -> str:
            lines = [f"ACTION: {action}", f"LANGUAGE: {S.lang_name(lang)}", f"DOCUMENT: «{meta['name']}» ({S.WRITING_TYPES[meta['type']]['label']})", f"PASSAGE KIND: {kind}"]
            if instruction:
                lines.append(f"AUTHOR'S INSTRUCTION: {instruction}")
            if action in ("expand", "describe", "continue", "shorten"):
                lines.append(f"TARGET LENGTH: about {want} words (between {lo} and {hi}).")
            if b_txt.strip():
                lines += ["", "TEXT BEFORE THE PASSAGE (for continuity only; do not repeat it):", b_txt.strip()]
            if a_txt.strip():
                lines += ["", "TEXT AFTER THE PASSAGE (for continuity only; do not repeat it):", a_txt.strip()]
            if action == "continue" and not selection.strip():
                lines += ["", "There is no selected passage: continue the text that comes right after the text above."]
            else:
                lines += ["", f"PASSAGE ({sel_words} words):", "<<<", selection.strip(), ">>>"]
            if draft is not None:
                lines += ["", "YOUR PREVIOUS RESULT:", "<<<", draft, ">>>", fix_note]
            lines += ["", "Reply with the resulting passage only."]
            return "\n".join(lines)

        creative = action not in ("fix",)
        res = self._clean(self._ask(system, user_msg(), max_new, 0.8 if creative else 0.2, progress=True))
        if not res:
            raise ProviderError("O modelo devolveu uma resposta vazia. Tente de novo (ou aumente a janela de contexto).")
        if action in ("expand", "describe", "continue", "shorten") and (selection or action == "continue"):   # tamanho escolhido: uma rodada de ajuste se ficou longe da meta
            n = S.count_words(res)
            if not (want * 0.8 <= n <= want * 1.3):
                self.check()
                note = f"Your previous result has {n} words; the target is {want} words (between {lo} and {hi}). Return the COMPLETE corrected passage."
                try:
                    new = self._clean(self._ask(system, user_msg(res, note), int(max_new * 1.15), 0.6, progress=True))
                except ContextTooLong:
                    new = ""
                if new and abs(S.count_words(new) - want) < abs(n - want):
                    res = new
        return res

    @staticmethod
    def _clean(raw: str) -> str:
        t = strip_reasoning(raw or "").strip()
        t = re.sub(r"^```\w*\n|\n```$", "", t).strip()
        t = D.clean(t)
        m = re.match(r"^<<<\s*\n?(.*?)\n?\s*>>>$", t, re.S)   # o modelo repetiu os delimitadores do prompt
        if m:
            t = m.group(1).strip()
        t = re.sub(r"\n{2,}", "\n", t)
        return t[:80000]

    def _edit_rules(self, action: str, selection: str, want: int, lang: str, meta: Dict[str, Any]) -> Dict[str, Any]:
        """Sem modelo: só o que dá para fazer com regras. O que exige criatividade devolve o texto igual e diz isso."""
        pt = S.lang_base(lang) == "pt"
        L_ = lambda a, c: a if pt else c   # noqa: E731
        if action in ("fix", "improve") and selection.strip():
            ps = selection.split("\n")
            fixed = ps
            for _ in range(3):   # achados vizinhos se sobrepõem: refaz até não sobrar nada para corrigir
                res = spell.proofread(fixed, lang, meta.get("ignore", []), use_dict=False)
                nxt = spell.apply_issues(fixed, res["issues"])
                if nxt == fixed:
                    break
                fixed = nxt
            new = "\n".join(spell.normalize_spacing(x, lang) for x in fixed)
            return {"text": new, "notes": [L_("Sem modelo de IA: só espaços, pontuação e maiúsculas foram corrigidos.", "No AI model: only spacing, punctuation and capitals were fixed.")], "changed": new != selection}
        if action == "shorten" and selection.strip():
            outp, n = [], 0
            for para in selection.split("\n"):
                kept = []
                for sent in re.split(r"(?<=[.!?…])\s+", para.strip()):
                    if n >= want and (kept or outp):
                        break
                    kept.append(sent)
                    n += S.count_words(sent)
                if kept:
                    outp.append(" ".join(kept))
                if n >= want:
                    break
            return {"text": "\n".join(outp), "notes": [L_("Sem modelo de IA: mantive as primeiras frases até o tamanho pedido.", "No AI model: kept the first sentences up to the requested size.")], "changed": True}
        return {"text": selection, "notes": [L_("Sem modelo de IA não dá para fazer isso: o texto ficou como estava. Baixe um modelo em Configurações → Modelo de texto (IA).",
                                                "This needs an AI model: the text was left as it was. Download one in Settings → Text model (AI).")], "changed": False}

    # ================================================================ EDIÇÃO: ortografia e gramática com IA
    def proofread_ai(self, pid: str) -> Dict[str, Any]:
        meta = self.mgr.meta(pid)
        b = self.opts.get("body") or {}
        lang = S.norm_lang(b.get("language") or meta["language"])
        paras = [str(x) for x in b.get("paragraphs")] if isinstance(b.get("paragraphs"), list) else D.plain_paragraphs(self.mgr.get_doc(pid)["blocks"])
        paras = paras[: spell.MAX_PARAS]
        base = spell.proofread(paras, lang, meta.get("ignore", []), use_dict=b.get("dictionary") is not False)
        n_ctx = int(self.settings["model"]["n_ctx"])
        chunk_chars = int(clamp(n_ctx * 0.25 * CHARS_PER_TOKEN, 1200, 6000))
        chunks: List[List[int]] = []
        cur, size = [], 0
        for i, s in enumerate(paras):
            if not s.strip():
                continue
            if cur and size + len(s) > chunk_chars:
                chunks.append(cur)
                cur, size = [], 0
            cur.append(i)
            size += len(s)
        if cur:
            chunks.append(cur)
        self.emit({"type": "start", "steps": [{"id": "rules", "label": "Regras e dicionário"}, {"id": "ai", "label": "Revisor ortográfico"}], "ai": self.live, "warning": "" if self.live else self.error})
        self.emit({"type": "step", "id": "rules", "label": "Regras e dicionário", "status": "done", "note": f"{len(base['issues'])} achado(s)" + ("" if base["dictionary"] else " · sem dicionário do sistema")})
        ai_issues: List[Dict[str, Any]] = []
        if self.live:
            system = system_message("proofreader", meta, self.content)
            total = min(len(chunks), 200)
            schema = {"type": "object", "properties": {"fixes": {"type": "array", "items": {"type": "object", "properties": {"i": {"type": "integer"}, "find": {"type": "string"}, "replace": {"type": "string"},
                      "kind": {"type": "string"}, "reason": {"type": "string"}}, "required": ["i", "find", "replace"]}}}, "required": ["fixes"]}
            for ci, idxs in enumerate(chunks[:200]):
                self.check()
                self.emit({"type": "progress", "done": ci, "total": total})
                user = f"LANGUAGE: {S.lang_name(lang)}\nPARAGRAPHS:\n" + json.dumps([{"i": i, "text": paras[i]} for i in idxs], ensure_ascii=False)
                try:
                    raw = self._ask(system, user, int(clamp(len(user) / CHARS_PER_TOKEN, 400, 3000)), 0.2, json_schema=schema)
                    fixes = self._valid_fixes(raw, paras, idxs)
                except (Cancelled, ContextTooLong):
                    raise
                except ProviderError as exc:
                    if str(exc) == "cancelado":
                        raise Cancelled() from None
                    self.warnings.append(str(exc)[:160])
                    fixes = []
                ai_issues += fixes
            self.emit({"type": "step", "id": "ai", "label": "Revisor ortográfico", "status": "done"})
        else:
            self.warnings.append(self.error or "Sem modelo: só as regras e o dicionário do sistema.")
        issues = spell.merge_issues(ai_issues, base["issues"])
        return self.done({"issues": issues[:2000], "dictionary": base["dictionary"], "language": lang, "paragraphs": len(paras), "counts": _count_kinds(issues)})

    @staticmethod
    def _valid_fixes(raw: str, paras: List[str], idxs: List[int]) -> List[Dict[str, Any]]:
        try:
            m = re.search(r"\{.*\}", strip_reasoning(raw), re.S)
            data = json.loads(m.group(0)) if m else {}
        except (ValueError, TypeError):
            return []
        fixes = data.get("fixes") if isinstance(data, dict) else None
        if not isinstance(fixes, list):
            return []
        out: List[Dict[str, Any]] = []
        for f in fixes[:200]:
            if not isinstance(f, dict):
                continue
            try:
                i = int(f.get("i"))
            except (TypeError, ValueError):
                continue
            find, rep = f.get("find"), f.get("replace")
            if i not in idxs or not isinstance(find, str) or not isinstance(rep, str) or not find or find == rep or len(find) > 300 or len(rep) > 400:
                continue
            st = paras[i].find(find)
            if st < 0:
                continue   # o modelo inventou um trecho que não existe: descartado
            kind = f.get("kind") if f.get("kind") in ("spelling", "grammar", "punctuation", "repetition") else "grammar"
            out.append({"p": i, "start": st, "end": st + len(find), "found": find, "fix": rep, "kind": kind, "msg": text(f.get("reason"), "", 120) or kind, "source": "ai"})
        return out


def _count_kinds(issues: List[Dict[str, Any]]) -> Dict[str, int]:
    c: Dict[str, int] = {}
    for i in issues:
        c[i["kind"]] = c.get(i["kind"], 0) + 1
    return c
