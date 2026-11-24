"""O teste de navegador (Playwright + Chromium) contra o servidor de verdade e um Hugging Face falso. Pulado se não há Node + Playwright."""
from __future__ import annotations

import os
import shutil
import subprocess
import unittest
from pathlib import Path

from tests.helpers import Env, LiveServer

ROOT = Path(__file__).resolve().parents[1]


def _has_playwright() -> bool:
    node = shutil.which("node")
    if not node:
        return False
    try:
        return subprocess.run([node, "-e", "require('playwright')"], capture_output=True, timeout=30, env=dict(os.environ)).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


@unittest.skipUnless(_has_playwright(), "precisa de Node + Playwright (NODE_PATH apontando para o node_modules que o tem)")
class BrowserTests(unittest.TestCase):
    def test_ui_smoke(self) -> None:
        env = Env(fake_hf=True)
        srv = LiveServer(env)
        try:
            r = subprocess.run(["node", str(ROOT / "tests" / "browser" / "ui_smoke.mjs"), srv.base], capture_output=True, text=True, timeout=240, env=dict(os.environ))
            self.assertEqual(r.returncode, 0, r.stdout + "\n" + r.stderr)
            self.assertIn("OK: ui_smoke", r.stdout)
        finally:
            srv.close()
            env.close()


    def test_ui_ai_with_a_fake_engine(self) -> None:
        """As ações da IA de ponta a ponta (editor → servidor → «modelo» → sugestão), com um llama_cpp falso."""
        import sys

        from tests.helpers import install_fake_llama

        old = sys.modules.get("llama_cpp")
        install_fake_llama()
        env = Env(fake_hf=True)
        (env.home / "models").mkdir(parents=True, exist_ok=True)
        (env.home / "models" / "Qwen3.5-2B-Heretic-Q4_K_M.gguf").write_bytes(b"GGUF" + b"0" * 1000)
        srv = LiveServer(env)
        try:
            r = subprocess.run(["node", str(ROOT / "tests" / "browser" / "ui_ai.mjs"), srv.base], capture_output=True, text=True, timeout=240, env=dict(os.environ))
            self.assertEqual(r.returncode, 0, r.stdout + "\n" + r.stderr)
            self.assertIn("OK: ui_ai", r.stdout)
        finally:
            srv.close()
            env.close()
            if old is None:
                sys.modules.pop("llama_cpp", None)
            else:
                sys.modules["llama_cpp"] = old


if __name__ == "__main__":
    unittest.main()
