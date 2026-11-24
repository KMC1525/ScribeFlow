"""Traduções, linha de comando e instaladores."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from tests.helpers import Env, FAKE_FILE_Q4, FAKE_REPO

ROOT = Path(__file__).resolve().parents[1]


class I18nTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "precisa de Node")
    def test_every_ui_string_has_an_english_translation(self) -> None:
        r = subprocess.run(["node", str(ROOT / "tests" / "js" / "i18n_check.mjs")], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertEqual(data["missing"], [], "frases sem tradução em scribeflow/web/js/en.js")
        self.assertEqual(data["empty"], [])

    @unittest.skipUnless(shutil.which("node"), "precisa de Node")
    def test_server_catalog_strings_are_translated(self) -> None:
        sys.path.insert(0, str(ROOT))
        from scribeflow import schema as S

        src = (ROOT / "scribeflow" / "web" / "js" / "en.js").read_text(encoding="utf-8")
        need = {v["label"] for v in S.WRITING_TYPES.values()} | {v["hint"] for v in S.WRITING_TYPES.values()} | {v["label"] for v in S.LANGUAGES.values()} | {v["label"] for v in S.PRESETS.values()}
        missing = [s for s in need if ("'" + s.replace("\\", "\\\\").replace("'", "\\'") + "':") not in src]
        self.assertEqual(missing, [])


class CLITests(unittest.TestCase):
    def run_cli(self, env: Env, *args: str, extra_env=None):
        e = dict(os.environ, SCRIBEFLOW_HOME=str(env.home), SCRIBEFLOW_LANG="en", PYTHONPATH=str(ROOT))
        e.update(extra_env or {})
        return subprocess.run([sys.executable, "-m", "scribeflow", *args], capture_output=True, text=True, timeout=120, env=e)

    def test_version_doctor_and_empty_lists(self) -> None:
        env = Env()
        try:
            self.assertIn("ScribeFlow 0.1.0", self.run_cli(env, "version").stdout)
            out = self.run_cli(env, "doctor").stdout
            self.assertIn("scribeflow models pull", out)
            self.assertIn("darrellbest/Qwen3.5-2B-Heretic-GGUF", out)
            self.assertIn("No projects", self.run_cli(env, "projects", "list").stdout)
        finally:
            env.close()

    def test_models_search_pull_use_rm_with_fake_hub(self) -> None:
        env = Env(fake_hf=True)
        try:
            e = {"HF_ENDPOINT": os.environ["HF_ENDPOINT"]}
            self.assertIn(FAKE_REPO, self.run_cli(env, "models", "search", "fakeorg", extra_env=e).stdout)
            r = self.run_cli(env, "models", "pull", FAKE_REPO, "--file", "Q8_0", extra_env=e)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("Tiny-Story-Q8_0.gguf", self.run_cli(env, "models", "list").stdout)
            # a seleção é a quantização pedida e fica em uso
            self.assertIn("* Tiny-Story-Q8_0.gguf", self.run_cli(env, "models", "list").stdout)
            r = self.run_cli(env, "models", "pull", "fakeorg/Pixel-Diffusion-GGUF", extra_env=e)
            self.assertNotEqual(r.returncode, 0)   # modelo de imagem: recusado
            self.assertIn("text", r.stderr.lower())
            self.assertEqual(self.run_cli(env, "models", "rm", "Tiny-Story-Q8_0.gguf").returncode, 0)
            self.assertNotIn("Tiny-Story", self.run_cli(env, "models", "list").stdout)
            # o padrão (darrellbest/…): baixa a quantização configurada (Q4_K_M), não o mmproj
            r = self.run_cli(env, "models", "pull", extra_env=e)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            lst = self.run_cli(env, "models", "list").stdout
            self.assertIn("Qwen3.5-2B-Heretic-Q4_K_M.gguf", lst)
            self.assertNotIn("mmproj", lst)
        finally:
            env.close()

    def test_projects_export_import_cli(self) -> None:
        env = Env()
        try:
            from scribeflow.storage import Store

            st = Store(env.home)
            m = st.projects.create("Via CLI", system_prompt="SP")
            out = env.home / "p.json"
            self.assertEqual(self.run_cli(env, "projects", "export", m["id"], "-o", str(out)).returncode, 0)
            self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["project"]["system_prompt"], "SP")
            r = self.run_cli(env, "projects", "import", str(out))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(len(Store(env.home).projects.list()), 2)
        finally:
            env.close()

    def test_engine_status_without_llama(self) -> None:
        env = Env()
        try:
            r = self.run_cli(env, "engine", "status")
            self.assertEqual(r.returncode, 0)
            self.assertTrue("NOT installed" in r.stdout or "installed:" in r.stdout)
        finally:
            env.close()


class InstallerTests(unittest.TestCase):
    def test_install_sh_is_valid_shell_and_brands_everything(self) -> None:
        sh = shutil.which("sh")
        self.assertIsNotNone(sh)
        self.assertEqual(subprocess.run([sh, "-n", str(ROOT / "install.sh")], capture_output=True).returncode, 0)
        for name in ("install.sh", "install.ps1"):
            text = (ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn("OpenFlow", text, name)
            self.assertNotIn("OPENFLOW", text, name)
            self.assertIn("ScribeFlow", text)
            self.assertIn("darrellbest/Qwen3.5-2B-Heretic-GGUF", text)
            self.assertNotRegex(text, r"\bflow (libs|native|models install)")

    def test_pyproject_exposes_the_commands_and_no_required_deps(self) -> None:
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('scribeflow = "scribeflow.cli:main"', text)
        self.assertIn("dependencies = []", text)

    def test_cloud_providers_are_gone_from_the_code(self) -> None:
        bad = ("api.openai.com", "api.anthropic.com", "generativelanguage.googleapis.com", "openrouter.ai", "lmstudio", "ollama")
        for p in (ROOT / "scribeflow").rglob("*"):
            if p.suffix in (".py", ".js", ".html") and "en.js" not in p.name:
                t = p.read_text(encoding="utf-8", errors="ignore").lower()
                for w in bad:
                    self.assertNotIn(w, t, f"{p.name}: {w}")


if __name__ == "__main__":
    unittest.main()
