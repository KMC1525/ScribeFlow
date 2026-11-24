# Changelog

Format: `## [version] — date`. Each version lists what changed for users and, honestly, what was **not** verified. [Português](CHANGELOG.md)

## [0.1.0] — 2026-11-24

First version. ScribeFlow is the **Scriber** of ASTA as an app of its own, with OpenFlow's project system and colors, and a local text model from Hugging Face.

### New
- **Web app and `scribeflow` command** (alias `scribe`), Windows · macOS · Linux, installed from the terminal (`install.sh` / `install.ps1`, which also install and update).
- **Editor from ASTA's Scriber, minus the *automatic generation* tab:** Word-like editor, paper formatting, find & replace, history, spell check (rules + system dictionary + browser), AI review, text statistics, web search/pinned sources, `.docx`/`.md`/`.txt`/`.html` export and import.
- **General system prompt** in place of the lorebooks: one text box per project that guides **every** AI action (improve, expand, rewrite, shorten, fix, continue, dialogue, describe, tone, translate, ask…) and the AI review. Saved with the project.
- **Projects as in OpenFlow:** one folder per project, home with search (title, description, system prompt and the text), sorting, create/rename/duplicate/delete.
- **Export / import of projects as JSON** (UI and `scribeflow projects export|import`): text, system prompt, formatting, pinned sources and history. Import always creates a new project and re-validates everything.
- **Only local text models from Hugging Face (GGUF).** No cloud or "frontier" providers exist. Default model: `darrellbest/Qwen3.5-2B-Heretic-GGUF` (Q4_K_M) with a **16K-token context window**.
- **Settings → Text model (AI):** switch the model, adjust the context window (4K…128K or any value), test, and a **search bar** that searches Hugging Face for text-generation models and **downloads directly** (quantization picker with the RAM-recommended one marked, parallel download with resume, GGUF check, cancel). Non-text repositories are refused; `mmproj` files are never offered.
- Settings for the editor, appearance (same palette as OpenFlow, light/dark/auto, scale, fonts) and advanced options (GPU layers, threads, idle unload, "thinking" on/off, Hugging Face token, models folder, web search, settings export/import).
- Terminal: `scribeflow models list|search|pull|use|rm`, `engine status|install`, `projects list|export|import`, `update`, `folder`, `doctor`, `version`.
- Portuguese-first interface with an English translation (checked by `node tests/js/i18n_check.mjs`).

### Removed from the Scriber (on purpose)
- The **automatic generation** tab (and its API: plan → write → review → package).
- The **lorebooks** (replaced by the general system prompt).
- The agent-team / effort picker (it was an ASTA-wide feature; ScribeFlow runs one small local model).
- Attachments in the prompt (they only served automatic generation).

### Not verified
- **No real generation was run.** Hugging Face was blocked in the build environment: the default model was never downloaded and `llama-cpp-python` was never compiled or run there. Download/search/listing were tested against a local fake Hub; model calls against a stand-in for `llama_cpp` (including the "thinking off" prompt). Support for the `qwen3.5` architecture depends on the llama.cpp bundled in the `llama-cpp-python` you install (`scribeflow engine install --upgrade`).
- **Only Linux was run** (35+ Python tests, a Chromium test of the whole interface, and the real `install.sh` into a temporary folder). `install.ps1` was never executed; macOS and Windows are covered only by the CI configuration, which has not run yet.
- The prebuilt `llama-cpp-python` package index was unreachable; the fallback build needs a C/C++ compiler and cmake.
- DuckDuckGo/Wikipedia web search was not exercised against the real sites.
