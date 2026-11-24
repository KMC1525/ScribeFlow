"""Ajudas dos testes: um Hugging Face falso (servidor HTTP local) e um servidor do ScribeFlow numa pasta temporária."""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional

FAKE_REPO = "fakeorg/Tiny-Story-GGUF"
FAKE_FILE_Q4 = "Tiny-Story-Q4_K_M.gguf"
FAKE_FILE_Q8 = "Tiny-Story-Q8_0.gguf"
IMG_REPO = "fakeorg/Pixel-Diffusion-GGUF"


def fake_gguf(size: int) -> bytes:
    return b"GGUF" + bytes((i * 7) % 251 for i in range(size - 4))


FILES = {FAKE_REPO: {FAKE_FILE_Q4: fake_gguf(300_000), FAKE_FILE_Q8: fake_gguf(500_000), "Tiny-Story-mmproj-F16.gguf": fake_gguf(100_000), "README.md": b"# fake"},
         IMG_REPO: {"Pixel-Q4_K_M.gguf": fake_gguf(200_000)}}
MODELS = {FAKE_REPO: {"id": FAKE_REPO, "downloads": 1234, "likes": 7, "pipeline_tag": "text-generation", "tags": ["gguf", "text-generation"]},
          IMG_REPO: {"id": IMG_REPO, "downloads": 99999, "likes": 70, "pipeline_tag": "text-to-image", "tags": ["gguf", "text-to-image"]},
          "darrellbest/Qwen3.5-2B-Heretic-GGUF": {"id": "darrellbest/Qwen3.5-2B-Heretic-GGUF", "downloads": 1600, "likes": 1, "pipeline_tag": "image-text-to-text", "tags": ["gguf", "image-text-to-text"]}}
FILES["darrellbest/Qwen3.5-2B-Heretic-GGUF"] = {"Qwen3.5-2B-Heretic-Q4_K_M.gguf": fake_gguf(260_000), "Qwen3.5-2B-Heretic-Q8_0.gguf": fake_gguf(400_000), "Qwen3.5-2B-Heretic-mmproj-F16.gguf": fake_gguf(90_000)}


class FakeHF(BaseHTTPRequestHandler):
    log: list = []

    def log_message(self, *a: Any) -> None:
        pass

    def _json(self, obj: Any, status: int = 200) -> None:
        data = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:   # noqa: N802
        FakeHF.log.append(self.path)
        sp = urllib.parse.urlsplit(self.path)
        q = urllib.parse.parse_qs(sp.query)
        path = sp.path
        if path == "/api/models":
            tag = (q.get("pipeline_tag") or [""])[0]
            term = ((q.get("search") or [""])[0]).lower()
            author = (q.get("author") or [""])[0].lower()
            rows = [m for m in MODELS.values() if (not tag or m["pipeline_tag"] == tag) and (not term or term in m["id"].lower()) and (not author or m["id"].lower().startswith(author + "/"))]
            return self._json(rows)
        m = re.match(r"^/api/models/([^/]+/[^/]+)/tree/main$", path)
        if m:
            repo = m.group(1)
            if repo not in FILES:
                return self._json({"error": "not found"}, 404)
            return self._json([{"type": "file", "path": n, "size": len(b), "lfs": {"size": len(b)}} for n, b in FILES[repo].items()])
        m = re.match(r"^/api/models/([^/]+/[^/]+)$", path)
        if m:
            repo = m.group(1)
            return self._json(MODELS[repo]) if repo in MODELS else self._json({"error": "Repository not found"}, 404)
        m = re.match(r"^/([^/]+/[^/]+)/resolve/main/(.+)$", path)
        if m:
            repo, name = m.group(1), urllib.parse.unquote(m.group(2))
            blob = FILES.get(repo, {}).get(name)
            if blob is None:
                return self._json({"error": "nope"}, 404)
            rng = re.match(r"^bytes=(\d+)-(\d*)$", self.headers.get("Range") or "")
            status, start, end = 200, 0, len(blob) - 1
            if rng:
                start = int(rng.group(1))
                end = min(int(rng.group(2)), len(blob) - 1) if rng.group(2) else len(blob) - 1
                status = 206
            body = blob[start:end + 1]
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{len(blob)}")
            self.end_headers()
            self.wfile.write(body)
            return
        self._json({"error": "unknown"}, 404)


def start_fake_hf() -> tuple:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeHF)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


class Env:
    """Uma pasta temporária de dados + (opcional) um Hugging Face falso apontado por HF_ENDPOINT."""

    def __init__(self, fake_hf: bool = False):
        self.home = Path(tempfile.mkdtemp(prefix="sf-test-"))
        self.hf_srv: Optional[ThreadingHTTPServer] = None
        self._old = os.environ.get("HF_ENDPOINT")
        if fake_hf:
            self.hf_srv, url = start_fake_hf()
            os.environ["HF_ENDPOINT"] = url
            from scribeflow import hf

            hf.HF = url
            hf.clear_cache()

    def close(self) -> None:
        if self.hf_srv:
            self.hf_srv.shutdown()
            self.hf_srv.server_close()
        if self._old is None:
            os.environ.pop("HF_ENDPOINT", None)
        else:
            os.environ["HF_ENDPOINT"] = self._old
        shutil.rmtree(self.home, ignore_errors=True)


class LiveServer:
    """O servidor do ScribeFlow de verdade (porta livre) numa pasta temporária."""

    def __init__(self, env: Env):
        from scribeflow.server import make_server
        from scribeflow.storage import Store

        self.store = Store(env.home)
        self.httpd, self.app = make_server("127.0.0.1", 0, self.store)
        self.port = self.httpd.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def call(self, method: str, path: str, body: Any = None, raw: Optional[bytes] = None, headers: Optional[Dict[str, str]] = None) -> Any:
        import urllib.error
        import urllib.request

        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        hdrs = {"Content-Type": "application/json"} if data is not None else {}
        hdrs.update(headers or {})
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                ct = r.headers.get("Content-Type", "")
                payload = r.read()
                return r.status, (json.loads(payload) if "json" in ct else payload)
        except urllib.error.HTTPError as e:
            payload = e.read()
            try:
                return e.code, json.loads(payload)
            except ValueError:
                return e.code, payload

    def wait_job(self, jid: str, timeout: float = 20) -> list:
        import time
        import urllib.request

        events = []
        with urllib.request.urlopen(self.base + f"/api/jobs/{jid}/events", timeout=timeout) as r:
            for line in r:
                line = line.decode().strip()
                if line.startswith("data: "):
                    ev = json.loads(line[6:])
                    events.append(ev)
                    if ev.get("type") == "end":
                        break
        return events

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


class FakeLlama:
    """Um `llama_cpp.Llama` de mentira: responde conforme a ação pedida no prompt e mostra se o system prompt do projeto chegou."""

    instances: list = []

    def __init__(self, **kw: Any):
        self.kw = kw
        self.prompts: list = []
        self.metadata = {"tokenizer.chat_template": "{% for m in messages %}<|im_start|>{{ m.role }}\n{{ m.content }}<|im_end|>\n{% endfor %}{% if add_generation_prompt %}<|im_start|>assistant\n{% if not enable_thinking %}<think>\n\n</think>\n\n{% endif %}{% endif %}"}
        FakeLlama.instances.append(self)

    def n_ctx(self) -> int:
        return int(self.kw["n_ctx"])

    def tokenize(self, b: bytes, add_bos: bool = True, special: bool = False) -> list:
        return list(range(len(b) // 3 + 1))

    def detokenize(self, ids: list) -> bytes:
        return b"<|im_end|>" if ids and ids[0] == 2 else b""

    def token_eos(self) -> int:
        return 2

    def token_bos(self) -> int:
        return -1

    def _reply(self, prompt: str) -> str:
        sp = " [guiado pelo system prompt]" if "REGRA-UNICA" in prompt else ""
        if "ACTION: expand" in prompt:
            return ("Ela atravessou a sala devagar, sentindo o frio do assoalho sob os pés descalços. A luz fraca da vela desenhava sombras longas nas paredes, e cada rangido da madeira parecia anunciar "
                    "alguém prestes a surgir do corredor escuro, onde o silêncio pesava mais que qualquer palavra." + sp)
        if "ACTION: shorten" in prompt:
            return "Ela entrou." + sp
        if "ACTION: dialogue" in prompt:
            return "— Quem está aí? — sussurrou ela.\n— Ninguém — respondeu a escuridão." + sp
        return "Ela entrou na sala e examinou tudo com cuidado." + sp

    def create_completion(self, prompt: str, stop: Any = None, stream: bool = False, grammar: Any = None, **kw: Any):
        self.prompts.append(prompt)
        if grammar is not None or "PARAGRAPHS:" in prompt:
            text = json.dumps({"fixes": [{"i": 0, "find": "ezemplo", "replace": "exemplo", "kind": "spelling", "reason": "erro de digitação"}]})
        else:
            text = self._reply(prompt)
        for i in range(0, len(text), 12):
            yield {"choices": [{"text": text[i:i + 12], "finish_reason": None}]}
        yield {"choices": [{"text": "", "finish_reason": "stop"}]}

    def create_chat_completion(self, messages: list, stream: bool = False, **kw: Any):
        prompt = "\n".join(str(m["content"]) for m in messages)
        for ch in self.create_completion(prompt, stream=True):
            yield {"choices": [{"delta": {"content": ch["choices"][0]["text"]}, "finish_reason": ch["choices"][0]["finish_reason"]}]}


def install_fake_llama() -> None:
    """Põe um `llama_cpp` falso nos módulos importados: o servidor «carrega» o modelo e gera de mentira."""
    import sys
    import types

    mod = types.ModuleType("llama_cpp")
    mod.Llama = FakeLlama   # type: ignore[attr-defined]
    mod.__version__ = "0.0-fake"   # type: ignore[attr-defined]
    mod.llama_supports_gpu_offload = lambda: False   # type: ignore[attr-defined]
    sys.modules["llama_cpp"] = mod
