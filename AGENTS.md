# AGENTS.md — ScribeFlow

Guide for people and AI agents working in this repository.

## What this is
ScribeFlow is a local-first writing app: the **Scriber** of [ASTA](https://github.com/KMC1525/ASTA) (minus *automatic generation*) with the project system and colors of [OpenFlow](https://github.com/KMC1525/OpenFlow). Python (standard library only) + a plain HTML/CSS/JS interface. The terminal command is `scribeflow` (alias `scribe`). The AI is **one local GGUF text model from Hugging Face**, run by `llama-cpp-python` (optional extra).

## Rules that must hold
- **Text models from Hugging Face only, local only.** No cloud/"frontier" providers, no API keys for models, no other model sources. Only `text-generation` / `image-text-to-text` repositories are searchable; everything else is refused by `hf.repo_info` (`REJECT_TAGS`). `mmproj` files are never offered.
- **Defaults:** model `darrellbest/Qwen3.5-2B-Heretic-GGUF` (`Q4_K_M`), context window **16384** (`storage.py`: `DEFAULT_MODEL_REPO`, `DEFAULT_MODEL_FILE`, `DEFAULT_N_CTX`); the window is user-adjustable and never overridden.
- **No automatic generation** and **no lorebooks.** The project's general `system_prompt` is injected into *every* AI call (`ai.system_message`) — keep it that way for new actions.
- **No required dependencies** in the Python core (extras only in `pyproject.toml`). Python ≥ 3.9 (no `match`, no runtime `X | Y`).
- **Strings are Portuguese-first with an English translation:** UI → `scribeflow/web/js/en.js` (`node tests/js/i18n_check.mjs`), terminal → `L("pt", "en")` in `cli.py`, installers → `L "pt" "en"`. Maps used with `t(variable)` live in DOM-free modules (`labels.js`, the label maps in `scriber_ui.js`) so the check can read them; server catalog labels are checked by `tests/test_misc.py`.
- **Keep install surfaces in sync** when behavior, commands, install steps or limits change: `README.md` + `README.pt-BR.md`, `CHANGELOG.md` + `CHANGELOG.en.md`, `install.sh`, `install.ps1`, `.github/workflows`. The version lives in `scribeflow/__init__.py`; write the changelog before bumping it.
- **Treat inputs as untrusted** (the browser, files, JSON imports, URLs, AI output): validate paths, sizes, types and JSON. The AI writes **text** (or a JSON the code validates, like the proofreader's `fixes`, each checked against the real paragraph); nothing it returns is executed. Editor/import/AI text goes through the block model (`docmodel`).
- **Local and private:** the server listens on `127.0.0.1` and checks `Host`/`Origin`; the Hugging Face token never reaches the browser; no telemetry; updates and uninstalls never delete user data (`~/.scribeflow`).
- **Honesty:** say in the docs and changelog what was not verified (real model runs, Windows/macOS, external services). Never claim what was not tested.
- Never remove existing functionality without authorization; never publish releases without it.

## Map
- `scribeflow/cli.py` — the `scribeflow` command · `server.py` — HTTP API + SSE jobs · `storage.py` — settings (defaults, validation, secret masking) · `projects.py` — project store, search, history, `.docx`/`.md`/`.txt`/`.html`, **JSON export/import**.
- `scribeflow/hf.py` (Hub search/listing/download) · `dl.py` (parallel resumable downloads) · `llm.py` (loads the GGUF, 16K window, "thinking off" prompt, one generation at a time) · `ai.py` + `prompts/*.md` (editor actions, proofreader) · `websearch.py`.
- `scribeflow/docmodel.py`, `docx.py`, `spell.py`, `stats.py`, `schema.py` — the document (blocks), `.docx`, spelling, statistics, writing types/formats.
- `scribeflow/web/` — `main.js` (router), `views/projects.js` (home + search), `views/project.js` + `views/scriber_edit.js` (editor), `views/scriber_system.js` (system prompt panel), `views/scriber_side.js` (AI/review/web panel), `views/settings.js` (model switch + Hugging Face search/download), `css/`.
- `tests/` — `python -m unittest discover -s tests -t .` (`tests/helpers.py` has a fake Hugging Face and a live-server helper; `tests/browser/ui_smoke.mjs` needs Node + Playwright + Chromium, with `NODE_PATH` pointing to it).
