<div align="center">

# ScribeFlow

**A text editor with a local AI — novels, reports, analyses, copy and academic papers — in your browser, with text models from Hugging Face.**

Write in a Word-like editor, select a paragraph or a line of dialogue and let the AI improve, expand, shorten, rewrite or fix just that part, guided by one **general system prompt** for the whole text. Everything runs on your computer. No accounts, no API keys, no cloud models, no telemetry.

[Install](#install) · [Use](#use) · [Model](#the-text-model) · [Projects](#projects) · [Settings](#settings) · [Data](#your-data) · [Development](#development) · [Changelog](CHANGELOG.en.md) · [Português](README.pt-BR.md)

`MIT` · `Windows` · `macOS` · `Linux` · `Python 3.9+` · `v0.1.0`

</div>

---

ScribeFlow is the **Scriber** of [ASTA](https://github.com/KMC1525/ASTA) turned into an app of its own (without the *automatic generation* tab), with the project system and the colors of [OpenFlow](https://github.com/KMC1525/OpenFlow): Python (standard library only) + a plain HTML/CSS/JS interface, one `scribeflow` command (short alias: `scribe`).

## Install

One command installs **and** updates (your data in `~/.scribeflow` is never touched):

```bash
curl -fsSL https://raw.githubusercontent.com/KMC1525/ScribeFlow/main/install.sh | sh        # Linux / macOS
```

```powershell
irm https://raw.githubusercontent.com/KMC1525/ScribeFlow/main/install.ps1 | iex             # Windows
```

The installer: finds (or installs) Python 3.9+, creates an isolated environment, installs ScribeFlow, installs the **local AI engine** (llama.cpp, through `llama-cpp-python`: a ready-made package when there is one, otherwise it builds it) and **asks** whether to download the default model (~1.3 GB). Then:

```bash
scribeflow            # opens http://localhost:8791 in your browser
```

Useful variables (all optional): `SCRIBEFLOW_ENGINE=yes|no|cpu|cuda|metal` · `SCRIBEFLOW_MODEL=ask|yes|no` · `SCRIBEFLOW_PYTHON=auto|keep` · `SCRIBEFLOW_SOURCE=<url|folder>` · `SCRIBEFLOW_FORCE=1` · `SCRIBEFLOW_LANG=pt|en`. Manual install: `pip install .` then `scribeflow engine install`.

> Without the engine or a model ScribeFlow still works: editor, spell checker, statistics, history and `.docx`/`.md`/`.txt`/`.html` export. Only the AI actions (except *Fix* and *Shorten*, which have rule-based fallbacks) need the model.

## Use

1. **Projects** (home): every text is a project — search by title, description, system prompt or *the text itself*, sort, create, duplicate, delete, **import/export as JSON**.
2. **Editor:** bold/italic/headings/lists/alignment/page break, find & replace, history, zoom, paper formatting (font, spacing, indent, margins, page size), spell check (browser + rules + system dictionary) and stats.
3. **General system prompt** (left panel): one free text box — style and voice, characters, world, rules, what to avoid. **Every AI action follows it.**
4. **AI actions** (right panel, or the floating bar over a selection): *Improve · Expand · Rewrite · Shorten · Fix · Continue · Turn into dialogue · Describe more · Change tone · Translate · Ask…*, with a chosen size for expansions (paragraphs and dialogue lines separately). Select freely, or turn on the *Paragraph* / *Dialogue* click modes. Accept, retry or discard — and Ctrl+Z undoes.
5. **Review:** rules + system dictionary, or *Review with AI* (grammar and agreement, each fix checked against the real text before it is offered).
6. **Web** (optional, off by default): search DuckDuckGo/Wikipedia, read a page, pin it as a source for the AI. The only thing besides Hugging Face that touches the internet.

## The text model

ScribeFlow uses **only text-generation models from Hugging Face**, in GGUF, running locally. There are no cloud or "frontier" providers.

- **Default model:** [`darrellbest/Qwen3.5-2B-Heretic-GGUF`](https://huggingface.co/darrellbest/Qwen3.5-2B-Heretic-GGUF) (`Q4_K_M`, ~1.3 GB), with a **16K-token context window**.
- **Settings → Text model (AI):** current model, *test*, **context window** (4K … 128K, or any number), downloaded models (use / delete), and a **search bar** that searches Hugging Face for text models (by name, author like `unsloth`, `owner/name` or a page URL), lists the quantizations of each repository (recommended for your RAM marked) and **downloads straight from there** with progress, resume and a file check. Image, video, voice and embedding repositories are refused.
- Terminal: `scribeflow models search qwen` · `models pull [owner/name] [--file Q4_K_M]` · `models list|use|rm`.
- Multimodal repositories (like the default, tagged `image-text-to-text`) work: only the text part is used and the `mmproj` file is never offered.

## Projects

Same system as OpenFlow: one folder per project under `~/.scribeflow/projects/<id>/` (`project.json`, `document.json`, `history/`, `exports/`). **Export / import as JSON** (menu of a card, or the editor menu): one file with the text, the system prompt, the formatting, pinned sources and history. Importing always creates a **new** project and re-validates everything (it never overwrites). CLI: `scribeflow projects list|export ID -o file.json|import file.json`.

## Settings

| Tab | What |
|---|---|
| **Text model (AI)** | model in use, context window, downloaded models, Hugging Face search & download |
| **Editor** | default type/language/content, expansion sizes, autosave, spell check, history size |
| **Appearance** | theme (dark/light/auto), accent, interface scale, density, font, language |
| **Advanced** | GPU layers, threads, idle unload, "thinking" models on/off, Hugging Face token, models folder, web search, export/import settings |

The Hugging Face token is stored only on your computer and is never sent to the browser.

## Your data

Everything is plain files in `~/.scribeflow` (override with `SCRIBEFLOW_HOME`): `settings.json`, `projects/`, `models/`. Updating or uninstalling never deletes them. The server listens on `127.0.0.1` only (and checks `Host`/`Origin`); text from the browser, the AI and imported files is validated through the block model before it is stored. No telemetry.

## Development

```bash
python -m unittest discover -s tests -t .      # Python tests (+ browser tests when Node + Playwright are available)
node tests/js/i18n_check.mjs                  # every UI string has an English translation
```

Layout: `scribeflow/` — `server.py` (HTTP + SSE), `projects.py` (project store), `hf.py`/`dl.py` (search & fast resumable downloads), `llm.py` (local model), `ai.py` + `prompts/` (editor actions), `docmodel.py`/`docx.py`/`spell.py`/`stats.py` (the document), `web/` (UI, no build step). See [AGENTS.md](AGENTS.md) and [CONTRIBUTING.md](CONTRIBUTING.md).

### What was not verified (please read)

- **A real generation with the default model was not run.** Hugging Face was unreachable from the environment where this was built, so the model was never downloaded and `llama-cpp-python` was never compiled or run there. Search, file listing and download were tested against a local fake server that mimics the Hub API (its shape was checked against the real default repository through the Hugging Face connector); the model calls were tested with a stand-in for `llama_cpp`. Whether the `llama-cpp-python` you install supports the `qwen3.5` architecture is up to its bundled llama.cpp — if loading fails, run `scribeflow engine install --upgrade`.
- **Only Linux was run.** The installers and the whole suite are set up in CI for Linux, macOS and Windows, but `install.ps1` was never executed (no PowerShell here) and the Windows/macOS paths are untested.
- The ready-made `llama-cpp-python` package index could not be reached, so the "prebuilt first, build if missing" path was not exercised; building needs a C/C++ compiler and cmake.
- The web search (DuckDuckGo/Wikipedia) was not exercised against the real sites.
