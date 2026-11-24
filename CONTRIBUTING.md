# Contributing to ScribeFlow

Thanks for helping! A short guide (the [Portuguese version](CONTRIBUTING.pt-BR.md) says the same).

- **Run the tests** before opening a pull request: `python -m unittest discover -s tests -t .` (the Chromium test runs when Node + Playwright are available; set `NODE_PATH` to the `node_modules` that has Playwright) and `node tests/js/i18n_check.mjs`.
- **Python ≥ 3.9**, standard library only in the core (extras live in `pyproject.toml`). No `match`, no runtime `X | Y`.
- **Local text models from Hugging Face only.** No cloud providers or API keys for models.
- **Strings:** the interface and the terminal are Portuguese-first with an English translation (`scribeflow/web/js/en.js`, `L("pt", "en")` in `cli.py`, installers use `L "pt" "en"`). A new phrase without a translation fails `tests/test_misc.py`.
- **Docs:** when behavior, install steps, commands or limits change, update `README.md` + `README.pt-BR.md` and `CHANGELOG.md` + `CHANGELOG.en.md` (per version: what changed and, honestly, what was not verified).
- **Safety:** treat files, JSON imports, URLs and AI output as untrusted (validate paths, sizes, types, JSON). The AI produces text (or data the code validates), never code to run.
- Regression fixes come with a test that reproduces the bug. Never claim in the docs what was not tested.
