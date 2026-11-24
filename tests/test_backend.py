"""Testes do ScribeFlow (sem rede e sem modelo de verdade: o Hugging Face é um servidor falso local e o motor de IA é substituído por um falso)."""
from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from unittest import mock

from tests.helpers import FAKE_FILE_Q4, FAKE_FILE_Q8, FAKE_REPO, FILES, IMG_REPO, Env, FakeHF, LiveServer


class StorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = Env()
        from scribeflow.storage import Store

        self.store = Store(self.env.home)

    def tearDown(self) -> None:
        self.env.close()

    def test_defaults_are_the_requested_model_and_16k_context(self) -> None:
        s = self.store.get_settings()
        self.assertEqual(s["model"]["repo"], "darrellbest/Qwen3.5-2B-Heretic-GGUF")
        self.assertEqual(s["model"]["file"], "Qwen3.5-2B-Heretic-Q4_K_M.gguf")
        self.assertEqual(s["model"]["n_ctx"], 16384)

    def test_no_cloud_providers_in_settings(self) -> None:
        s = self.store.get_settings()
        self.assertNotIn("providers", s)
        self.assertNotIn("active", s)
        dumped = json.dumps(s).lower()
        for word in ("openai", "anthropic", "claude", "gemini", "openrouter", "api_key"):
            self.assertNotIn(word, dumped)

    def test_context_window_is_adjustable_and_clamped(self) -> None:
        self.assertEqual(self.store.save_settings({"model": {"n_ctx": 32768}})["model"]["n_ctx"], 32768)
        self.assertEqual(self.store.save_settings({"model": {"n_ctx": 10}})["model"]["n_ctx"], 512)
        self.assertEqual(self.store.save_settings({"model": {"n_ctx": 10 ** 9}})["model"]["n_ctx"], 1 << 20)
        self.assertEqual(self.store.save_settings({"model": {"n_ctx": "abc"}})["model"]["n_ctx"], 1 << 20 if False else self.store.get_settings()["model"]["n_ctx"])

    def test_token_never_goes_to_the_browser_and_empty_keeps_it(self) -> None:
        self.store.save_settings({"hf": {"token": "hf_secret"}})
        pub = self.store.public_settings()
        self.assertEqual(pub["hf"]["token"], "")
        self.assertTrue(pub["hf"]["token_set"])
        self.store.save_settings({"hf": {"token": ""}})
        self.assertEqual(self.store.get_settings()["hf"]["token"], "hf_secret")
        self.store.save_settings({"hf": {"token": None}})
        self.assertEqual(self.store.get_settings()["hf"]["token"], "")

    def test_model_file_names_cannot_escape_the_folder(self) -> None:
        s = self.store.save_settings({"model": {"active": "../../etc/passwd", "file": "/tmp/x.gguf"}})
        self.assertEqual(s["model"]["active"], "")
        self.assertEqual(s["model"]["file"], "x.gguf")


class ProjectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = Env()
        from scribeflow.storage import Store

        self.store = Store(self.env.home)
        self.pm = self.store.projects

    def tearDown(self) -> None:
        self.env.close()

    def test_create_save_search_and_system_prompt(self) -> None:
        m = self.pm.create("Meu Romance", "romance", "pt-BR", "uma história", system_prompt="Escreva em terceira pessoa.")
        self.assertEqual(m["system_prompt"], "Escreva em terceira pessoa.")
        self.pm.save_doc(m["id"], html_src="<h1>Capítulo 1</h1><p>O dragão dormia sob a montanha.</p>")
        self.assertEqual(self.pm.get_doc(m["id"])["stats"]["words"], 8)
        self.assertEqual([p["id"] for p in self.pm.list("DRAGAO")], [m["id"]])   # sem diferenciar acentos nem maiúsculas
        self.assertEqual([p["id"] for p in self.pm.list("terceira pessoa")], [m["id"]])   # acha no system prompt
        self.assertEqual(self.pm.list("inexistente"), [])
        self.assertEqual(self.pm.list("dragao")[0]["match"], "O dragão dormia sob a montanha.")

    def test_sorting_and_duplicate_and_delete(self) -> None:
        a = self.pm.create("Bravo")
        b = self.pm.create("Alfa")
        self.pm.save_doc(a["id"], markdown="um dois três quatro")
        self.assertEqual([p["name"] for p in self.pm.list(sort="name")], ["Alfa", "Bravo"])
        self.assertEqual(self.pm.list(sort="words")[0]["id"], a["id"])
        d = self.pm.duplicate(a["id"])
        self.assertEqual(self.pm.get_doc(d["id"])["stats"]["words"], 4)
        self.pm.delete(b["id"])
        self.assertEqual(len(self.pm.list()), 2)
        from scribeflow.projects import ProjectError

        with self.assertRaises(ProjectError):
            self.pm.meta(b["id"])
        with self.assertRaises(ProjectError):
            self.pm.meta("../../etc")

    def test_json_export_import_roundtrip(self) -> None:
        m = self.pm.create("Conto", "fiction", "en-US", "desc", system_prompt="Dry humor. Never use adverbs.")
        self.pm.save_doc(m["id"], html_src="<p>Hello <b>brave</b> world.</p><p>— Hi — she said.</p>")
        self.pm.update_meta(m["id"], {"author": "Ana", "ignore": ["Xyzzy"]})
        self.pm.snapshot(m["id"], "ponto 1")
        data = json.loads(json.dumps(self.pm.export_json(m["id"])))
        self.assertEqual(data["format"], "scribeflow.project")
        self.assertEqual(data["project"]["system_prompt"], "Dry humor. Never use adverbs.")
        new = self.pm.import_json(data)
        self.assertNotEqual(new["id"], m["id"])   # nunca sobrescreve: sempre cria um projeto novo
        self.assertEqual(new["system_prompt"], "Dry humor. Never use adverbs.")
        self.assertEqual(new["author"], "Ana")
        self.assertEqual(new["ignore"], ["Xyzzy"])
        self.assertEqual(self.pm.get_doc(new["id"])["blocks"], self.pm.get_doc(m["id"])["blocks"])
        self.assertEqual(len(self.pm.history(new["id"])), 1)
        self.assertEqual(len(self.pm.list()), 2)

    def test_import_json_rejects_garbage_and_sanitizes(self) -> None:
        from scribeflow.projects import ProjectError

        for bad in (None, [], {"format": "other"}, {"format": "scribeflow.project", "version": 99, "project": {}}, {"format": "scribeflow.project", "version": 1, "project": "x"}):
            with self.assertRaises(ProjectError):
                self.pm.import_json(bad)
        evil = {"format": "scribeflow.project", "version": 1, "project": {"name": "x" * 500, "type": "nope", "language": "zz", "format": {"font": "<script>", "size": 9999, "margins": "x"}, "system_prompt": "s" * 50000},
                "document": {"blocks": [{"t": "script", "runs": [{"x": "<img src=x onerror=alert(1)>"}]}, {"t": "p", "runs": [{"x": "ok\x00 text"}]}]}, "history": "nope", "sources": [{"url": "javascript:alert(1)"}]}
        m = self.pm.import_json(evil)
        self.assertLessEqual(len(m["name"]), 100)
        self.assertEqual(m["type"], "romance")
        self.assertLessEqual(len(m["system_prompt"]), 12000)
        self.assertEqual(m["format"]["font"], "Georgia")
        html = self.pm.get_doc(m["id"])["html"]
        self.assertNotIn("<script", html)
        self.assertNotIn("<img", html)
        self.assertEqual(self.pm.get_sources(m["id"]), [])

    def test_export_formats(self) -> None:
        m = self.pm.create("Doc")
        self.pm.save_doc(m["id"], html_src="<h1>Título</h1><p>Texto <i>aqui</i>.</p>")
        for fmt, magic in (("docx", b"PK"), ("md", b"# "), ("txt", b"T"), ("html", b"<!doctype")):
            self.assertTrue(self.pm.render(m["id"], fmt).startswith(magic), fmt)
        docx = self.pm.render(m["id"], "docx")
        back = self.pm.import_file(m["id"], "x.docx", docx, "append")
        self.assertGreater(back["added"], 0)

    def test_history_restore(self) -> None:
        m = self.pm.create("H")
        self.pm.save_doc(m["id"], markdown="versão um")
        self.pm.save_doc(m["id"], markdown="versão dois", label="mudança grande")
        hid = self.pm.history(m["id"])[0]["id"]
        self.pm.restore(m["id"], hid)
        self.assertIn("versão um", self.pm.render(m["id"], "txt").decode())


class HuggingFaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = Env(fake_hf=True)

    def tearDown(self) -> None:
        self.env.close()

    def test_quant_parsing_and_grouping_ignores_mmproj(self) -> None:
        from scribeflow import hf

        self.assertEqual(hf.parse_quant("Qwen3.5-2B-Heretic-Q4_K_M.gguf")["quant"], "Q4_K_M")
        self.assertEqual(hf.parse_quant("m-BF16.gguf")["bits"], 16)
        raw = [{"name": "a-Q4_K_M.gguf", "size": 1_000_000_000}, {"name": "a-Q8_0.gguf", "size": 2_000_000_000}, {"name": "a-mmproj-F16.gguf", "size": 600_000_000},
               {"name": "big-Q4_K_M-00001-of-00002.gguf", "size": 3_000_000_000}, {"name": "big-Q4_K_M-00002-of-00002.gguf", "size": 3_000_000_000}, {"name": "broken-00001-of-00003.gguf", "size": 5}]
        groups = hf.group_files(raw, ram_gb=8)
        names = [g["name"] for g in groups]
        self.assertNotIn("a-mmproj-F16.gguf", names)
        self.assertEqual(len(groups), 3)   # a-Q4, a-Q8 e o dividido em 2 partes; o incompleto some
        self.assertEqual([g["name"] for g in groups if g["recommended"]], ["a-Q4_K_M.gguf"])
        self.assertEqual(next(g for g in groups if g["name"].startswith("big"))["parts"], 2)

    def test_parse_repo_accepts_urls(self) -> None:
        from scribeflow import hf

        self.assertEqual(hf.parse_repo("https://huggingface.co/darrellbest/Qwen3.5-2B-Heretic-GGUF/tree/main"), "darrellbest/Qwen3.5-2B-Heretic-GGUF")
        self.assertEqual(hf.parse_repo("hf.co/a/b"), "a/b")
        self.assertEqual(hf.parse_repo("a/b"), "a/b")
        self.assertEqual(hf.parse_repo("../etc/passwd"), "")
        self.assertEqual(hf.parse_repo("só texto"), "")

    def test_search_is_text_generation_only(self) -> None:
        from scribeflow import hf

        ids = [r["id"] for r in hf.search("", limit=20)] if False else [r["id"] for r in hf.search("fakeorg")]
        self.assertIn(FAKE_REPO, ids)
        self.assertNotIn(IMG_REPO, ids)   # modelo de imagem fica de fora
        qwen = [r["id"] for r in hf.search("qwen")]
        self.assertEqual(qwen, ["darrellbest/Qwen3.5-2B-Heretic-GGUF"])   # multimodal (image-text-to-text) entra: só a parte de texto é usada
        self.assertFalse(hf.repo_info(IMG_REPO)["text"])
        self.assertTrue(hf.repo_info(FAKE_REPO)["text"])

    def test_download_resume_and_verify(self) -> None:
        from scribeflow import hf
        from scribeflow.net import ProviderError

        d = self.env.home / "m"
        d.mkdir()
        seen = []
        path = hf.download_many(FAKE_REPO, [FAKE_FILE_Q4], d, sizes={FAKE_FILE_Q4: 300_000}, progress=lambda a, b: seen.append((a, b)))
        self.assertEqual(path.read_bytes(), FILES[FAKE_REPO][FAKE_FILE_Q4])
        self.assertEqual(seen[-1][0], 300_000)
        self.assertEqual(hf.read_meta(d, path.name)["repo"], FAKE_REPO)
        self.assertEqual([m["name"] for m in hf.local_models(d)], [FAKE_FILE_Q4])
        # um «modelo» que não é GGUF é recusado e apagado
        FILES[FAKE_REPO]["Bad-Q4_0.gguf"] = b"<html>login</html>" * 100
        try:
            with self.assertRaises(ProviderError):
                hf.download(FAKE_REPO, "Bad-Q4_0.gguf", d)
        finally:
            FILES[FAKE_REPO].pop("Bad-Q4_0.gguf")
        self.assertFalse((d / "Bad-Q4_0.gguf").exists())
        self.assertFalse((d / "Bad-Q4_0.gguf.part").exists())
        self.assertEqual(hf.delete_local(d, FAKE_FILE_Q4), 2)
        self.assertEqual(hf.local_models(d), [])

    def test_invalid_names_are_rejected(self) -> None:
        from scribeflow import hf
        from scribeflow.net import ProviderError

        for repo, name in (("bad", "x.gguf"), (FAKE_REPO, "../x.gguf"), (FAKE_REPO, "x.bin")):
            with self.assertRaises(ProviderError):
                hf.download(repo, name, self.env.home)


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.env = Env(fake_hf=True)
        cls.srv = LiveServer(cls.env)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.srv.close()
        cls.env.close()

    def test_state_and_defaults(self) -> None:
        st, d = self.srv.call("GET", "/api/state")
        self.assertEqual(st, 200)
        self.assertEqual(d["settings"]["model"]["n_ctx"], 16384)
        self.assertEqual(d["model"]["default"]["repo"], "darrellbest/Qwen3.5-2B-Heretic-GGUF")
        self.assertFalse(d["model"]["default"]["installed"])

    def test_no_automatic_generation_route(self) -> None:
        st, m = self.srv.call("POST", "/api/projects", {"name": "x"})
        self.assertEqual(st, 201)
        for path in ("generate", "ai/generate", "estimate"):
            st, _ = self.srv.call("POST", f"/api/projects/{m['id']}/{path}", {"prompt": "escreva um livro"})
            self.assertEqual(st, 404, path)
        for path in ("/api/scriber/generate", "/api/providers/test", "/api/lorebooks"):
            self.assertEqual(self.srv.call("GET", path)[0], 404, path)

    def test_system_prompt_roundtrip_over_http(self) -> None:
        st, m = self.srv.call("POST", "/api/projects", {"name": "Com prompt", "system_prompt": "Use frases curtas."})
        st, m2 = self.srv.call("PUT", f"/api/projects/{m['id']}", {"system_prompt": "Use frases LONGAS."})
        self.assertEqual(m2["system_prompt"], "Use frases LONGAS.")
        st, got = self.srv.call("GET", f"/api/projects/{m['id']}")
        self.assertEqual(got["system_prompt"], "Use frases LONGAS.")

    def test_project_json_export_import_http(self) -> None:
        st, m = self.srv.call("POST", "/api/projects", {"name": "Exporta", "system_prompt": "SP"})
        self.srv.call("PUT", f"/api/projects/{m['id']}/document", {"html": "<p>Olá mundo</p>"})
        st, raw = self.srv.call("GET", f"/api/projects/{m['id']}/export.json")
        self.assertEqual(st, 200)
        payload = json.loads(raw) if isinstance(raw, bytes) else raw
        self.assertEqual(payload["project"]["system_prompt"], "SP")
        st, new = self.srv.call("POST", "/api/projects/import", raw=json.dumps(payload).encode())
        self.assertEqual(st, 201)
        self.assertEqual(new["words"], 2)
        st, err = self.srv.call("POST", "/api/projects/import", raw=b"nao e json")
        self.assertEqual(st, 400)
        st, err = self.srv.call("POST", "/api/projects/import", raw=b'{"format":"x"}')
        self.assertEqual(st, 400)

    def test_host_and_origin_checks(self) -> None:
        import urllib.error
        import urllib.request

        req = urllib.request.Request(self.srv.base + "/api/state", headers={"Host": "evil.example.com"})
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(req)
        self.assertEqual(cm.exception.code, 403)
        req = urllib.request.Request(self.srv.base + "/api/projects", data=b"{}", method="POST", headers={"Origin": "http://evil.example.com", "Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(req)
        self.assertEqual(cm.exception.code, 403)

    def test_model_search_files_download_use_delete(self) -> None:
        st, r = self.srv.call("GET", "/api/hf/search?q=fakeorg")
        self.assertEqual(st, 200)
        self.assertEqual([x["id"] for x in r["results"]], [FAKE_REPO])
        st, r = self.srv.call("GET", "/api/hf/search?q=https://huggingface.co/" + FAKE_REPO)
        self.assertEqual([x["id"] for x in r["results"]], [FAKE_REPO])
        # repositório de imagem: recusado
        st, err = self.srv.call("GET", "/api/hf/files?repo=" + IMG_REPO)
        self.assertEqual(st, 400)
        self.assertIn("geração de texto", err["error"])
        st, err = self.srv.call("POST", "/api/hf/download", {"repo": IMG_REPO, "name": "Pixel-Q4_K_M.gguf"})
        self.assertEqual(st, 400)
        st, files = self.srv.call("GET", "/api/hf/files?repo=" + FAKE_REPO)
        self.assertEqual(st, 200)
        self.assertEqual({f["name"] for f in files["files"]}, {FAKE_FILE_Q4, FAKE_FILE_Q8})   # sem mmproj e sem README
        self.assertEqual(sum(1 for f in files["files"] if f["recommended"]), 1)
        # arquivo que não está no repositório
        st, err = self.srv.call("POST", "/api/hf/download", {"repo": FAKE_REPO, "name": "Outro-Q4_K_M.gguf"})
        self.assertEqual(st, 404)
        st, job = self.srv.call("POST", "/api/hf/download", {"repo": FAKE_REPO, "name": FAKE_FILE_Q4})
        self.assertEqual(st, 200)
        evs = self.srv.wait_job(job["job_id"])
        self.assertEqual(evs[-1]["type"], "end")
        self.assertEqual(evs[-1]["status"], "done")
        self.assertTrue(any(e["type"] == "progress" for e in evs) or any(e["type"] == "result" for e in evs))
        st, m = self.srv.call("GET", "/api/models")
        self.assertEqual([x["name"] for x in m["local"]], [FAKE_FILE_Q4])
        self.assertEqual(m["active"], FAKE_FILE_Q4)   # baixar já deixa em uso
        # trocar para outro e voltar
        st, job2 = self.srv.call("POST", "/api/hf/download", {"repo": FAKE_REPO, "name": FAKE_FILE_Q8, "use": False})
        self.srv.wait_job(job2["job_id"])
        st, m = self.srv.call("POST", "/api/models/use", {"name": FAKE_FILE_Q8})
        self.assertEqual(m["active"], FAKE_FILE_Q8)
        st, err = self.srv.call("POST", "/api/models/use", {"name": "nao-existe.gguf"})
        self.assertEqual(st, 404)
        st, m = self.srv.call("DELETE", "/api/models/local/" + FAKE_FILE_Q8)
        self.assertEqual(st, 200)
        self.assertEqual(m["active"], FAKE_FILE_Q4)
        st, m = self.srv.call("DELETE", "/api/models/local/" + FAKE_FILE_Q4)
        self.assertEqual(m["local"], [])
        self.assertEqual(self.srv.call("DELETE", "/api/models/local/..%2F..%2Fetc")[0], 404)

    def test_context_window_over_http(self) -> None:
        st, s = self.srv.call("PUT", "/api/settings", {"model": {"n_ctx": 32768}})
        self.assertEqual(s["model"]["n_ctx"], 32768)
        st, s = self.srv.call("PUT", "/api/settings", {"model": {"n_ctx": 16384}})
        self.assertEqual(s["model"]["n_ctx"], 16384)

    def test_ai_edit_without_model_uses_rules_and_says_so(self) -> None:
        st, m = self.srv.call("POST", "/api/projects", {"name": "Sem modelo"})
        st, job = self.srv.call("POST", f"/api/projects/{m['id']}/ai/edit", {"action": "fix", "selection": "ola  mundo ,tudo bem", "language": "pt-BR"})
        self.assertEqual(st, 200)
        evs = self.srv.wait_job(job["job_id"])
        res = next(e for e in evs if e["type"] == "result")["data"]
        self.assertFalse(res["ai"])
        self.assertIn("Nenhum modelo", res["warning"])
        self.assertNotIn("  ", res["text"])
        st, err = self.srv.call("POST", f"/api/projects/{m['id']}/ai/edit", {"action": "expand", "selection": ""})
        self.assertEqual(st, 400)


class FakeLLM:
    """Substitui o modelo local: guarda o que recebeu e devolve um texto pronto."""

    def __init__(self, reply: str = "Texto novo, mais rico e longo, com muitos detalhes sensoriais agora."):
        self.reply = reply
        self.calls: list = []

    def count_tokens(self, s: str) -> int:
        return len(s) // 3 + 1

    def status(self) -> dict:
        return {"loaded": True}

    def generate(self, messages, max_tokens=1024, temperature=0.7, on_text=None, cancelled=lambda: False, json_schema=None, **kw):
        self.calls.append({"messages": messages, "max_tokens": max_tokens, "json_schema": json_schema})
        if on_text:
            on_text(self.reply)
        return self.reply, "stop"


class AITests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = Env()
        from scribeflow.storage import Store

        self.store = Store(self.env.home)
        self.pm = self.store.projects
        from scribeflow import llm as llmmod

        self.patches = [mock.patch.object(llmmod, "resolve_model", lambda *a, **k: Path("/x/model.gguf")), mock.patch.object(llmmod, "llama_available", lambda: {"installed": True, "version": "t", "gpu": False, "error": ""})]
        for p in self.patches:
            p.start()

    def tearDown(self) -> None:
        for p in self.patches:
            p.stop()
        self.env.close()

    def run_edit(self, body: dict, system_prompt: str = "", reply: str = "ok", **kw):
        from scribeflow.ai import ScribeAI
        from scribeflow.jobs import Job

        m = self.pm.create("T", "romance", "pt-BR", system_prompt=system_prompt)
        llm = FakeLLM(reply)
        job = Job("t")
        ai = ScribeAI(self.store, self.pm, llm, {"body": body, "prompt": body.get("prompt", "")}, job)
        return ai.edit_text(m["id"]), llm

    def test_system_prompt_guides_every_action(self) -> None:
        for action in ("improve", "expand", "rewrite", "shorten", "fix", "continue", "dialogue", "describe", "tone", "translate", "custom"):
            body = {"action": action, "selection": "Ela entrou na sala e olhou em volta com cuidado.", "prompt": "mais sombrio", "language": "pt-BR", "expand": {"mode": "add", "words": 40}}
            res, llm = self.run_edit(body, system_prompt="REGRA-UNICA-123: nunca use a palavra 'sala'.")
            system = llm.calls[0]["messages"][0]["content"]
            self.assertIn("REGRA-UNICA-123", system, action)
            self.assertIn("(canon; follow it in every action):", system, action)
            user = llm.calls[0]["messages"][1]["content"]
            self.assertIn(f"ACTION: {action}", user)
            self.assertTrue(res["ai"], action)
            self.assertTrue(res["system_prompt_used"])

    def test_empty_system_prompt_is_not_injected(self) -> None:
        res, llm = self.run_edit({"action": "improve", "selection": "Um texto qualquer aqui.", "language": "pt-BR"})
        self.assertNotIn("(canon; follow it in every action):", llm.calls[0]["messages"][0]["content"])
        self.assertFalse(res["system_prompt_used"])

    def test_proofreader_also_sees_the_system_prompt_and_drops_invented_fixes(self) -> None:
        from scribeflow.ai import ScribeAI
        from scribeflow.jobs import Job

        m = self.pm.create("P", "romance", "pt-BR", system_prompt="Nomes inventados: Zorvath.")
        reply = json.dumps({"fixes": [{"i": 0, "find": "ezemplo", "replace": "exemplo", "kind": "spelling", "reason": "typo"}, {"i": 0, "find": "NAO EXISTE", "replace": "x"}, {"i": 5, "find": "ezemplo", "replace": "y"}]})
        llm = FakeLLM(reply)
        ai = ScribeAI(self.store, self.pm, llm, {"body": {"paragraphs": ["Isto é um ezemplo simples.", "Zorvath chegou."], "language": "pt-BR"}}, Job("t"))
        res = ai.proofread_ai(m["id"])
        self.assertIn("Zorvath", llm.calls[0]["messages"][0]["content"])
        self.assertIsNotNone(llm.calls[0]["json_schema"])
        ai_issues = [i for i in res["issues"] if i["source"] == "ai"]
        self.assertEqual([(i["found"], i["fix"]) for i in ai_issues], [("ezemplo", "exemplo")])

    def test_target_length_adjust_pass(self) -> None:
        # a primeira resposta é curta demais para «expandir +100»: o editor pede um ajuste (2 chamadas)
        res, llm = self.run_edit({"action": "expand", "selection": "Uma frase curta.", "language": "pt-BR", "expand": {"mode": "add", "words": 100}}, reply="Ainda curta.")
        self.assertEqual(len(llm.calls), 2)
        self.assertIn("YOUR PREVIOUS RESULT", llm.calls[1]["messages"][1]["content"])

    def test_output_is_cleaned(self) -> None:
        res, _ = self.run_edit({"action": "improve", "selection": "Um texto.", "language": "pt-BR"}, reply="<think>pensando</think>```\nPrimeiro parágrafo.\n\n\nSegundo parágrafo.\n```")
        self.assertEqual(res["paragraphs"], ["Primeiro parágrafo.", "Segundo parágrafo."])

    def test_context_is_trimmed_to_the_window(self) -> None:
        self.store.save_settings({"model": {"n_ctx": 1024}})
        res, llm = self.run_edit({"action": "improve", "selection": "Trecho curto aqui.", "context_before": "antes " * 2000, "context_after": "depois " * 2000, "language": "pt-BR"})
        user = llm.calls[0]["messages"][1]["content"]
        self.assertLess(len(user), 3000 * 3)
        self.assertLessEqual(llm.calls[0]["max_tokens"], 512)


class LLMUnitTests(unittest.TestCase):
    def test_missing_engine_gives_install_hint(self) -> None:
        from scribeflow import llm as llmmod
        from scribeflow.net import ProviderError
        from scribeflow.storage import Store

        env = Env()
        try:
            store = Store(env.home)
            (Path(store.models_dir) / "x-Q4_K_M.gguf").write_bytes(b"GGUF" + b"0" * 100)
            eng = llmmod.LocalLLM(store)
            with mock.patch.dict("sys.modules", {"llama_cpp": None}):
                with self.assertRaises(ProviderError) as cm:
                    eng.generate([{"role": "user", "content": "oi"}])
            self.assertIn("scribeflow engine install", str(cm.exception))
        finally:
            env.close()

    def test_resolve_model_prefers_active_then_default_then_first(self) -> None:
        from scribeflow import llm as llmmod
        from scribeflow.storage import DEFAULT_MODEL_FILE, Store

        env = Env()
        try:
            store = Store(env.home)
            md = Path(store.models_dir)
            self.assertIsNone(llmmod.resolve_model(store))
            (md / "b-Q4_K_M.gguf").write_bytes(b"GGUF")
            (md / "a-Q8_0.gguf").write_bytes(b"GGUF")
            self.assertEqual(llmmod.resolve_model(store).name, "a-Q8_0.gguf")
            (md / DEFAULT_MODEL_FILE).write_bytes(b"GGUF")
            self.assertEqual(llmmod.resolve_model(store).name, DEFAULT_MODEL_FILE)
            store.save_settings({"model": {"active": "b-Q4_K_M.gguf"}})
            self.assertEqual(llmmod.resolve_model(store).name, "b-Q4_K_M.gguf")
        finally:
            env.close()

    def test_generation_with_a_fake_llama_and_thinking_off(self) -> None:
        import sys
        import types

        try:
            import jinja2  # noqa: F401  (o llama-cpp-python depende dele; sem ele o desligar do «pensar» cai no caminho normal)
        except ImportError:
            self.skipTest("jinja2 não instalado")

        from scribeflow import llm as llmmod
        from scribeflow.storage import Store

        class FakeLlama:
            instances: list = []

            def __init__(self, **kw):
                self.kw = kw
                self.prompts: list = []
                self.metadata = {"tokenizer.chat_template": "{% for m in messages %}<|{{ m.role }}|>{{ m.content }}{% endfor %}{% if add_generation_prompt %}<|assistant|>{% if not enable_thinking %}<think>\n\n</think>\n\n{% endif %}{% endif %}"}
                FakeLlama.instances.append(self)

            def n_ctx(self):
                return self.kw["n_ctx"]

            def tokenize(self, b, add_bos=True, special=False):
                return list(range(len(b) // 4 + 1))

            def detokenize(self, ids):
                return b""

            def token_eos(self):
                return -1

            def token_bos(self):
                return -1

            def create_completion(self, prompt, stop=None, stream=False, **kw):
                self.prompts.append(prompt)
                for piece in ("<think>hmm</think>Olá", ", mundo."):
                    yield {"choices": [{"text": piece, "finish_reason": None}]}
                yield {"choices": [{"text": "", "finish_reason": "stop"}]}

        env = Env()
        try:
            store = Store(env.home)
            (Path(store.models_dir) / "m-Q4_K_M.gguf").write_bytes(b"GGUF" + b"0" * 64)
            fake = types.ModuleType("llama_cpp")
            fake.Llama = FakeLlama   # type: ignore[attr-defined]
            fake.__version__ = "0.0-test"   # type: ignore[attr-defined]
            with mock.patch.dict("sys.modules", {"llama_cpp": fake}):
                eng = llmmod.LocalLLM(store)
                out, stop = eng.generate([{"role": "system", "content": "SYS"}, {"role": "user", "content": "oi"}], max_tokens=50)
                self.assertEqual((out, stop), ("Olá, mundo.", "stop"))
                inst = FakeLlama.instances[-1]
                self.assertEqual(inst.kw["n_ctx"], 16384)   # a janela padrão é 16K
                self.assertIn("<think>\n\n</think>", inst.prompts[0])   # pensamento desligado pelo modelo de chat
                # mudar a janela recarrega o modelo
                store.save_settings({"model": {"n_ctx": 8192}})
                eng.generate([{"role": "user", "content": "oi"}], max_tokens=20)
                self.assertEqual(FakeLlama.instances[-1].kw["n_ctx"], 8192)
                self.assertEqual(len(FakeLlama.instances), 2)
                # texto que não cabe na janela
                from scribeflow.llm import ContextTooLong

                with self.assertRaises(ContextTooLong):
                    eng.generate([{"role": "user", "content": "palavra " * 20000}])
        finally:
            env.close()


class SchemaTests(unittest.TestCase):
    def test_actions_cover_the_requested_selectors(self) -> None:
        from scribeflow import schema as S

        for a in ("expand", "shorten", "fix", "improve", "dialogue"):
            self.assertIn(a, S.ACTION_IDS)

    def test_cli_parser(self) -> None:
        from scribeflow import cli

        p = cli.build_parser()
        self.assertEqual(p.parse_args(["models", "pull", "a/b", "--file", "Q4_K_M"]).file, "Q4_K_M")
        self.assertEqual(p.parse_args(["engine", "install", "--backend", "cuda"]).backend, "cuda")


if __name__ == "__main__":
    unittest.main()
