#!/bin/sh
# ScribeFlow — instalador/atualizador para Linux e macOS (comando `scribeflow`).
#
#   curl -fsSL https://raw.githubusercontent.com/KMC1525/ScribeFlow/main/install.sh | sh
#
# O MESMO comando instala e atualiza. Seus dados (~/.scribeflow: projetos, modelos, configurações) nunca são tocados.
# Opções (variáveis de ambiente):
#   SCRIBEFLOW_ENGINE=yes|no|cpu|cuda|metal   motor de IA local (llama.cpp, pelo pacote llama-cpp-python). Padrão: yes (escolhe o certo para o seu computador:
#                                       Metal no Mac, CUDA se houver placa NVIDIA, senão CPU; tenta um pacote pronto e só compila se não houver). no: pula.
#   SCRIBEFLOW_MODEL=ask|yes|no         baixa o modelo de texto padrão do Hugging Face (darrellbest/Qwen3.5-2B-Heretic-GGUF, Q4_K_M, ~1,3 GB).
#                                       ask (padrão): pergunta no terminal; yes: baixa sem perguntar; no: pula (dá para baixar depois nas Configurações).
#   SCRIBEFLOW_SOURCE=<url|pasta|requisito>   instala de outra origem (padrão: GitHub, branch main)
#   SCRIBEFLOW_APP_DIR=<pasta>          onde fica o programa (padrão: ~/.scribeflow/app)
#   SCRIBEFLOW_BIN_DIR=<pasta>          onde ficam os comandos `scribeflow` e `scribe` (padrão: ~/.local/bin)
#   SCRIBEFLOW_PYTHON=auto|keep         auto (padrão): instala o Python se faltar (apt, dnf, yum, pacman, zypper, apk, Homebrew). keep: nunca mexe no Python do sistema.
#   SCRIBEFLOW_FORCE=1                  reinstala mesmo que a versão instalada já seja a mais recente.
# Argumentos: sh -s -- --run   abre o ScribeFlow ao terminar.
set -eu

SOURCE="${SCRIBEFLOW_SOURCE:-https://github.com/KMC1525/ScribeFlow/archive/refs/heads/main.zip}"
APP_DIR="${SCRIBEFLOW_APP_DIR:-$HOME/.scribeflow/app}"
BIN_DIR="${SCRIBEFLOW_BIN_DIR:-$HOME/.local/bin}"
RUN=0
for arg in "$@"; do [ "$arg" = "--run" ] && RUN=1; done

# Idioma dos textos = idioma do computador (pt ou en). SCRIBEFLOW_LANG=pt|en força. Vale também para o `scribeflow` chamado daqui.
detect_lang() {
  for v in "${SCRIBEFLOW_LANG:-}" "${LC_ALL:-}" "${LC_MESSAGES:-}" "${LANGUAGE:-}" "${LANG:-}"; do
    case "$v" in ""|C|POSIX|C.*) continue ;; pt*|PT*) echo pt; return ;; *) echo en; return ;; esac
  done
  if [ "$(uname -s)" = "Darwin" ] && command -v defaults >/dev/null 2>&1; then
    case "$(defaults read -g AppleLanguages 2>/dev/null | tr -d '() ",\n' | cut -c1-2)" in pt) echo pt; return ;; esac
  fi
  echo en
}
SF_L="$(detect_lang)"
export SCRIBEFLOW_LANG="$SF_L"
L() { if [ "$SF_L" = "pt" ]; then printf '%s' "$1"; else printf '%s' "$2"; fi; }

say()  { printf '\033[1m%s\033[0m\n' "$*"; }
note() { printf '  %s\n' "$*"; }
die()  { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

say "$(L "ScribeFlow — instalação/atualização" "ScribeFlow — install/update")"

# macOS: o Terminal nem sempre tem o Homebrew no PATH (Apple Silicon: /opt/homebrew; Intel: /usr/local).
if [ "$(uname -s)" = "Darwin" ]; then
  for brewbin in /opt/homebrew/bin/brew /usr/local/bin/brew; do
    if [ -x "$brewbin" ] && ! command -v brew >/dev/null 2>&1; then eval "$("$brewbin" shellenv)"; fi
  done
  PATH="$PATH:/opt/homebrew/bin:/usr/local/bin:/Library/Frameworks/Python.framework/Versions/Current/bin"; export PATH
fi

# 1) Python 3.9+ — instala se faltar, usando o gerenciador de pacotes do sistema (pode pedir a sua senha: sudo).
# macOS sem as «Command Line Tools»: /usr/bin/python3 é só um atalho que ABRE uma janela de instalação em vez de rodar o Python. Não o executamos.
mac_stub() {
  [ "$(uname -s)" = "Darwin" ] || return 1
  case "$(command -v "$1" 2>/dev/null)" in
    /usr/bin/python3|/usr/bin/python) ! xcode-select -p >/dev/null 2>&1 ;;
    *) return 1 ;;
  esac
}
find_python() {
  PY=""
  for cand in python3.14 python3.13 python3.12 python3.11 python3.10 python3.9 python3 python; do
    mac_stub "$cand" && continue
    if command -v "$cand" >/dev/null 2>&1 && "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1; then
      PY="$cand"; return 0
    fi
  done
  return 1
}
as_root() {
  if [ "$(id -u)" = "0" ]; then "$@"
  elif command -v sudo >/dev/null 2>&1; then sudo "$@"
  else return 1; fi
}
pkg_python() {
  case "$(uname -s)" in
    Darwin) command -v brew >/dev/null 2>&1 || return 1; brew install python ;;
    *)
      if command -v apt-get >/dev/null 2>&1; then as_root apt-get update -qq && as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-venv python3-pip
      elif command -v dnf >/dev/null 2>&1; then as_root dnf install -y python3 python3-pip
      elif command -v yum >/dev/null 2>&1; then as_root yum install -y python3 python3-pip
      elif command -v pacman >/dev/null 2>&1; then as_root pacman -S --noconfirm --needed python python-pip
      elif command -v zypper >/dev/null 2>&1; then as_root zypper --non-interactive install --no-recommends python3 python3-pip
      elif command -v apk >/dev/null 2>&1; then as_root apk add python3 py3-pip
      else return 1; fi ;;
  esac
}
python_hint() {
  case "$(uname -s)" in
    Darwin) echo "brew install python   (ou https://www.python.org/downloads/)" ;;
    *)      echo "sudo apt install python3 python3-venv python3-pip   (Debian/Ubuntu)  ·  sudo dnf install python3   (Fedora)  ·  sudo pacman -S python   (Arch)" ;;
  esac
}
PYMODE="${SCRIBEFLOW_PYTHON:-auto}"
if ! find_python; then
  [ "$PYMODE" = "keep" ] && die "$(L "Python 3.9 ou superior não encontrado. Instale com: $(python_hint)" "Python 3.9 or newer not found. Install with: $(python_hint)")"
  note "$(L "Python 3.9+ não encontrado — instalando …" "Python 3.9+ not found — installing …")"
  pkg_python >/dev/null || true
  find_python || die "$(L "Não consegui instalar o Python 3.9+ automaticamente. Instale com: $(python_hint)" "Could not install Python 3.9+ automatically. Install with: $(python_hint)")"
fi
note "Python: $($PY --version 2>&1)"

# 2) ambiente isolado (não suja o Python do sistema). Se o Python ficou mais novo, o ambiente é recriado.
mkdir -p "$APP_DIR"
PYV="$("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
VENVPY="$APP_DIR/venv/bin/python"
if [ -e "$APP_DIR/venv" ]; then
  VV="$("$VENVPY" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || true)"
  if [ -z "$VV" ] || "$PY" -c 'import sys; a, b = (tuple(map(int, v.split("."))) for v in sys.argv[1:3]); sys.exit(0 if a < b else 1)' "$VV" "$PYV"; then
    note "$(L "Recriando o ambiente para o Python $PYV (antes: ${VV:-quebrado}) …" "Recreating the environment for Python $PYV (before: ${VV:-broken}) …")"
    rm -rf "$APP_DIR/venv"
  fi
fi
if [ -x "$VENVPY" ]; then
  note "$(L "Ambiente já existe ($APP_DIR/venv) — reaproveitando." "Environment already exists ($APP_DIR/venv) — reusing it.")"
else
  note "$(L "Criando ambiente em $APP_DIR/venv …" "Creating environment in $APP_DIR/venv …")"
  "$PY" -m venv "$APP_DIR/venv" >/dev/null 2>&1 || {
    rm -rf "$APP_DIR/venv"
    if [ "$PYMODE" != "keep" ] && pkg_python >/dev/null 2>&1 && "$PY" -m venv "$APP_DIR/venv" >/dev/null 2>&1; then :; else
      rm -rf "$APP_DIR/venv"
      die "$(L "Não foi possível criar o ambiente virtual. No Debian/Ubuntu instale: sudo apt install python3-venv" "Could not create the virtual environment. On Debian/Ubuntu install: sudo apt install python3-venv")"
    fi
  }
fi
"$VENVPY" -m pip install --upgrade --quiet --disable-pip-version-check pip setuptools wheel >/dev/null 2>&1 \
  || note "$(L "⚠ Não foi possível atualizar o pip/setuptools/wheel agora (sem internet?); seguindo." "⚠ Could not update pip/setuptools/wheel right now (no internet?); continuing.")"

# 3) instala / atualiza o ScribeFlow
SPEC="scribeflow"
case "$SOURCE" in
  *://*|git+*) REQ="$SPEC @ $SOURCE" ;;
  /*|./*|../*|~*) REQ="$SPEC @ file://$(cd "$SOURCE" && pwd)" ;;
  *) REQ="$SOURCE" ;;
esac
OLD="$("$VENVPY" -I -c 'import scribeflow; print(scribeflow.__version__)' 2>/dev/null || true)"
SKIP=0
if [ -n "$OLD" ] && [ -x "$APP_DIR/venv/bin/scribeflow" ] && [ "${SCRIBEFLOW_FORCE:-0}" = "0" ] && [ -z "${SCRIBEFLOW_SOURCE:-}" ]; then
  REMOTE="$("$VENVPY" -I -c '
import re, urllib.request
try:
    with urllib.request.urlopen("https://raw.githubusercontent.com/KMC1525/ScribeFlow/main/scribeflow/__init__.py", timeout=20) as r:
        m = re.search(r"__version__\s*=\s*[\"\x27]([^\"\x27]+)", r.read(8192).decode("utf-8", "replace"))
    print(m.group(1) if m else "")
except Exception:
    print("")
' 2>/dev/null || true)"
  if [ -n "$REMOTE" ] && "$VENVPY" -I -c 'import re, sys
t = lambda v: tuple(int(x) for x in re.findall(r"\d+", v)[:4])
sys.exit(0 if t(sys.argv[1]) <= t(sys.argv[2]) else 1)' "$REMOTE" "$OLD"; then SKIP=1; fi
fi
if [ "$SKIP" = "1" ]; then
  note "$(L "ScribeFlow $OLD já instalado e na versão mais recente — nada a baixar." "ScribeFlow $OLD already installed and up to date — nothing to download.")"
else
  note "$(L "Baixando e instalando o ScribeFlow …" "Downloading and installing ScribeFlow …")"
  "$VENVPY" -m pip install --upgrade --disable-pip-version-check --quiet --no-cache-dir "$REQ" \
    || die "$(L "Falha ao instalar. Verifique sua conexão e tente de novo." "Installation failed. Check your connection and try again.")"
fi
NEW="$("$VENVPY" -I -c 'import scribeflow; print(scribeflow.__version__)')"

# 4) comandos `scribeflow` e `scribe`
mkdir -p "$BIN_DIR"
ln -sf "$APP_DIR/venv/bin/scribeflow" "$BIN_DIR/scribeflow"
ln -sf "$APP_DIR/venv/bin/scribe" "$BIN_DIR/scribe"
if [ -z "$OLD" ]; then say "$(L "✓ ScribeFlow $NEW instalado." "✓ ScribeFlow $NEW installed.")"; elif [ "$OLD" = "$NEW" ]; then say "$(L "✓ ScribeFlow $NEW já estava atualizado." "✓ ScribeFlow $NEW was already up to date.")"; else say "$(L "✓ ScribeFlow atualizado: $OLD → $NEW." "✓ ScribeFlow updated: $OLD → $NEW.")"; fi

# 5) motor de IA local (llama.cpp). Um pacote pronto é tentado primeiro; compilar só se não houver (precisa de compilador C/C++ e cmake).
ENGINE_FAILED=0
case "${SCRIBEFLOW_ENGINE:-yes}" in
  no|none|0) note "$(L "Motor de IA: pulado (SCRIBEFLOW_ENGINE=${SCRIBEFLOW_ENGINE})." "AI engine: skipped (SCRIBEFLOW_ENGINE=${SCRIBEFLOW_ENGINE}).")" ;;
  cpu|cuda|metal) say "$(L "Motor de IA local (llama.cpp, $SCRIBEFLOW_ENGINE) …" "Local AI engine (llama.cpp, $SCRIBEFLOW_ENGINE) …")"; "$APP_DIR/venv/bin/scribeflow" engine install --backend "$SCRIBEFLOW_ENGINE" || ENGINE_FAILED=1 ;;
  *) say "$(L "Motor de IA local (llama.cpp) …" "Local AI engine (llama.cpp) …")"; "$APP_DIR/venv/bin/scribeflow" engine install || ENGINE_FAILED=1 ;;
esac

# 6) modelo de texto padrão (Hugging Face). Sem SCRIBEFLOW_MODEL, PERGUNTA no terminal antes de baixar.
MODEL_FAILED=0
ASK="${SCRIBEFLOW_MODEL:-ask}"
if [ "$ASK" = "ask" ]; then
  if [ -r /dev/tty ] && [ -t 1 ]; then
    printf '%s' "$(L "Baixar agora o modelo de texto padrão (darrellbest/Qwen3.5-2B-Heretic-GGUF, ~1,3 GB)? [S/n] " "Download the default text model now (darrellbest/Qwen3.5-2B-Heretic-GGUF, ~1.3 GB)? [Y/n] ")"
    read -r ans < /dev/tty || ans=""
    case "$ans" in n|N|no|NO|nao|não|Nao|Não) ASK=no ;; *) ASK=yes ;; esac
  else ASK=no; note "$(L "Sem terminal para perguntar: o modelo não foi baixado (rode: scribeflow models pull)." "No terminal to ask: the model was not downloaded (run: scribeflow models pull).")"; fi
fi
case "$ASK" in
  yes|1|all) say "$(L "Baixando o modelo de texto padrão …" "Downloading the default text model …")"; "$APP_DIR/venv/bin/scribeflow" models pull || MODEL_FAILED=1 ;;
  *) note "$(L "Modelo: pulado. Baixe depois em Configurações → Modelo de texto (IA), ou:  scribeflow models pull" "Model: skipped. Download it later in Settings → Text model (AI), or:  scribeflow models pull")" ;;
esac
[ "$ENGINE_FAILED" = "1" ] && note "$(L "⚠ O motor de IA não foi instalado (veja acima). O editor já funciona; para tentar de novo:  scribeflow engine install" "⚠ The AI engine was not installed (see above). The editor already works; to try again:  scribeflow engine install")"
[ "$MODEL_FAILED" = "1" ] && note "$(L "⚠ O modelo não foi baixado (veja acima). Para tentar de novo:  scribeflow models pull" "⚠ The model was not downloaded (see above). To try again:  scribeflow models pull")"

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) case "${SHELL:-}" in
       */zsh)  RCFILE="~/.zshrc" ;;
       */bash) if [ "$(uname -s)" = "Darwin" ]; then RCFILE="~/.bash_profile"; else RCFILE="~/.bashrc"; fi ;;
       */fish) RCFILE="" ;;
       *)      RCFILE="~/.profile" ;;
     esac
     note "$(L "Adicione ao seu PATH para usar o comando 'scribeflow':" "Add this to your PATH to use the 'scribeflow' command:")"
     if [ -z "$RCFILE" ]; then note "$(L "  fish_add_path $BIN_DIR   (e abra um novo terminal)" "  fish_add_path $BIN_DIR   (and open a new terminal)")"
     else note "  echo 'export PATH=\"$BIN_DIR:\$PATH\"' >> $RCFILE   $(L "(e abra um novo terminal)" "(and open a new terminal)")"; fi
     note "$(L "Até lá, abra o ScribeFlow com o caminho completo:  $BIN_DIR/scribeflow" "Until then, open ScribeFlow with the full path:  $BIN_DIR/scribeflow")" ;;
esac
echo
note "$(L "Para abrir o ScribeFlow:   scribeflow" "To open ScribeFlow:   scribeflow")"
note "$(L "Para atualizar:   rode este mesmo comando de novo (ou: scribeflow update)" "To update:   run this same command again (or: scribeflow update)")"
echo

if [ "$RUN" = "1" ]; then exec "$APP_DIR/venv/bin/scribeflow"; fi
