# ScribeFlow — instalador/atualizador para Windows (PowerShell 5.1+).
#
#   irm https://raw.githubusercontent.com/KMC1525/ScribeFlow/main/install.ps1 | iex
#
# O MESMO comando instala e atualiza. Seus dados (%USERPROFILE%\.scribeflow: projetos, modelos, configurações) nunca são tocados.
# Variáveis opcionais: $env:SCRIBEFLOW_ENGINE = "yes" (padrão: instala o motor de IA local, llama.cpp pelo pacote llama-cpp-python; escolhe CUDA se houver placa NVIDIA, senão CPU;
#                                         tenta um pacote pronto e só compila se não houver) | "cpu" | "cuda" | "no" (pula)
#                      $env:SCRIBEFLOW_MODEL = "ask" (padrão: PERGUNTA no terminal antes de baixar o modelo de texto padrão do Hugging Face,
#                                         darrellbest/Qwen3.5-2B-Heretic-GGUF, Q4_K_M, ~1,3 GB) | "yes" (baixa sem perguntar) | "no" (pula)
#                      $env:SCRIBEFLOW_PYTHON = "auto" (padrão: instala o Python se faltar, pelo winget) | "keep" (nunca mexe no Python do sistema)
#                      $env:SCRIBEFLOW_SOURCE = <url|pasta>   (padrão: GitHub, branch main)
#                      $env:SCRIBEFLOW_FORCE = "1" → reinstala mesmo que a versão instalada já seja a mais recente.
#                      $env:SCRIBEFLOW_LANG = "pt" | "en" → idioma dos textos (padrão: o idioma do computador).

# 'Continue' de propósito: no Windows PowerShell 5.1, com 'Stop' qualquer texto que um programa externo (python, pip, winget) escreva no stderr
# vira uma exceção (NativeCommandError). Os erros que importam são checados por $LASTEXITCODE e por -ErrorAction Stop.
$ErrorActionPreference = 'Continue'
# Windows PowerShell 5.1 em Windows 10 antigo / Server 2016 só liga o TLS 1.2 se pedirem: sem isto o download do GitHub falha.
try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch { }
$Source = if ($env:SCRIBEFLOW_SOURCE) { $env:SCRIBEFLOW_SOURCE } else { 'https://github.com/KMC1525/ScribeFlow/archive/refs/heads/main.zip' }
$Root   = Join-Path $env:LOCALAPPDATA 'ScribeFlow'
$AppDir = Join-Path $Root 'app'
$BinDir = Join-Path $Root 'bin'

# Idioma dos textos = idioma do computador (pt ou en). $env:SCRIBEFLOW_LANG = "pt" | "en" força. O `scribeflow` chamado daqui lê a mesma variável.
$SfLang = 'en'
try {
  $forced = "$($env:SCRIBEFLOW_LANG)".ToLower()
  if ($forced) { $SfLang = if ($forced -like 'pt*') { 'pt' } else { 'en' } }
  else { $SfLang = if ((Get-UICulture).Name -like 'pt*') { 'pt' } else { 'en' } }
} catch { }
$env:SCRIBEFLOW_LANG = $SfLang
function L($pt, $en) { if ($SfLang -eq 'pt') { return $pt } else { return $en } }

function Say($m)  { Write-Host $m -ForegroundColor White }
function Note($m) { Write-Host "  $m" }
function Die($m)  { Write-Host "✗ $m" -ForegroundColor Red; throw $m }

Say (L 'ScribeFlow — instalação/atualização' 'ScribeFlow — install/update')

# 1) Python 3.9+ — instala se faltar e atualiza (o winget também atualiza o pip que vem com ele). $env:SCRIBEFLOW_PYTHON = "keep": nunca mexe no Python do sistema.
$PyMode = if ($env:SCRIBEFLOW_PYTHON) { $env:SCRIBEFLOW_PYTHON } else { 'auto' }
function Find-Python {
  foreach ($cand in @(@('py', '-3'), @('python'), @('python3'))) {
    try {
      $exe = $cand[0]; $args0 = @($cand | Select-Object -Skip 1)
      & $exe @args0 -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" 2>$null
      if ($LASTEXITCODE -eq 0) { return ,@(@($exe) + $args0) }   # a vírgula mantém o ARRAY: com um só elemento («python») o PowerShell o transformava na string «python», e $py[0] virava «p»
    } catch { }
  }
  return $null
}
function Refresh-Path { $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User') }
function Winget-Python($mode) {
  # winget (vem com o Windows 10/11): "install" instala o Python 3.12; "upgrade" atualiza as versões do Python instaladas por ele
  if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { return $false }
  $flags = @('--exact', '--silent', '--accept-package-agreements', '--accept-source-agreements')
  $prev = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
  try {
    if ($mode -eq 'install') { & winget install --id Python.Python.3.12 @flags | Out-Null; return ($LASTEXITCODE -eq 0) }
    foreach ($id in @('Python.Python.3.13', 'Python.Python.3.12', 'Python.Python.3.11', 'Python.Python.3.10', 'Python.Python.3.9')) {
      & winget list --id $id --exact 2>$null | Out-Null
      if ($LASTEXITCODE -eq 0) { & winget upgrade --id $id @flags | Out-Null }
    }
    return $true
  } finally { $ErrorActionPreference = $prev }
}
$py = Find-Python
if ($py) {
  if ($PyMode -ne 'keep') {
    $pyBefore = "$(& $py[0] @($py | Select-Object -Skip 1) --version)"
    Note (L "Python já instalado ($pyBefore) — verificando se há versão mais nova …" "Python already installed ($pyBefore) — checking for a newer version …")
    if (Winget-Python 'upgrade') {
      Refresh-Path; $py = Find-Python
      $pyAfter = "$(& $py[0] @($py | Select-Object -Skip 1) --version)"
      if ($pyAfter -ne $pyBefore) { Note (L "Python atualizado: $pyBefore → $pyAfter" "Python updated: $pyBefore → $pyAfter") } else { Note (L 'Python já está na versão mais recente disponível.' 'Python is already at the latest available version.') }
    } else { Note (L 'Não foi possível atualizar o Python automaticamente (sem o winget); seguindo com o atual.' 'Could not update Python automatically (no winget); continuing with the current one.') }
  }
} else {
  if ($PyMode -eq 'keep') { Die (L 'Python 3.9 ou superior não encontrado. Instale com:  winget install Python.Python.3.12   (ou https://www.python.org/downloads/) e rode este comando de novo.' 'Python 3.9 or newer not found. Install with:  winget install Python.Python.3.12   (or https://www.python.org/downloads/) and run this command again.') }
  Note (L 'Python 3.9+ não encontrado — instalando com o winget …' 'Python 3.9+ not found — installing with winget …')
  [void](Winget-Python 'install'); Refresh-Path; $py = Find-Python
  if (-not $py) { Die (L 'Não consegui instalar o Python 3.9+ automaticamente. Instale com:  winget install Python.Python.3.12   (ou https://www.python.org/downloads/) e rode este comando de novo.' 'Could not install Python 3.9+ automatically. Install with:  winget install Python.Python.3.12   (or https://www.python.org/downloads/) and run this command again.') }
}
Note ("Python: " + (& $py[0] @($py | Select-Object -Skip 1) --version))

# 2) ambiente isolado. Se o Python foi atualizado para uma versão mais nova, o ambiente é recriado.
New-Item -ItemType Directory -Force -ErrorAction Stop -Path $AppDir, $BinDir | Out-Null
$venv = Join-Path $AppDir 'venv'
$venvPy = Join-Path $venv 'Scripts\python.exe'
$pyV = (& $py[0] @($py | Select-Object -Skip 1) -c "import sys; print('%d.%d' % sys.version_info[:2])").Trim()
if (Test-Path $venv) {
  $vv = $null
  try { $vv = (& $venvPy -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null) } catch { }
  $vv = if ($vv) { "$vv".Trim() } else { '' }
  if ((-not $vv) -or ([version]$vv -lt [version]$pyV)) {
    Note (L "Recriando o ambiente para o Python $pyV (antes: $(if ($vv) { $vv } else { 'quebrado' })) — as bibliotecas serão reinstaladas …" "Recreating the environment for Python $pyV (before: $(if ($vv) { $vv } else { 'broken' })) — the libraries will be reinstalled …")
    try { Remove-Item -Recurse -Force -ErrorAction Stop $venv }
    catch { Die (L "Não consegui apagar o ambiente antigo ($venv): algum programa o está usando. Feche o ScribeFlow (e os terminais com o scribeflow aberto) e rode este comando de novo." "Could not delete the old environment ($venv): a program is using it. Close ScribeFlow (and any terminal running scribeflow) and run this command again.") }
  }
}
if (Test-Path $venvPy) { Note (L "Ambiente já existe ($venv) — reaproveitando." "Environment already exists ($venv) — reusing it.") }
else {
  Note (L "Criando ambiente em $venv …" "Creating environment in $venv …")
  & $py[0] @($py | Select-Object -Skip 1) -m venv $venv
  if ($LASTEXITCODE -ne 0) { Die (L 'Não foi possível criar o ambiente virtual.' 'Could not create the virtual environment.') }
}
# ferramentas do Python (pip, setuptools, wheel) sempre na versão mais recente
$prevEap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
& $venvPy -m pip install --upgrade --quiet --disable-pip-version-check pip setuptools wheel 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { Note (L '⚠ Não foi possível atualizar o pip/setuptools/wheel agora (sem internet?); seguindo.' '⚠ Could not update pip/setuptools/wheel right now (no internet?); continuing.') }
$ErrorActionPreference = $prevEap

# 3) instala / atualiza o ScribeFlow
$spec = 'scribeflow'
if ($Source -match '://') { $req = "$spec @ $Source" }
elseif (Test-Path $Source) { $req = "$spec @ " + ([System.Uri](Resolve-Path -ErrorAction Stop $Source).Path).AbsoluteUri }
else { $req = $Source }
$old = & $venvPy -I -c "import scribeflow; print(scribeflow.__version__)" 2>$null   # ainda não instalado: o Python escreve um erro no stderr, que é descartado
if ($LASTEXITCODE -ne 0) { $old = $null }
# Só baixa se não está instalado ou se há uma versão mais nova (com a origem padrão a versão publicada é consultada). SCRIBEFLOW_FORCE=1 sempre reinstala.
$skip = $false
$force = $env:SCRIBEFLOW_FORCE -and ($env:SCRIBEFLOW_FORCE -ne '0')
if ($old -and (Test-Path (Join-Path $venv 'Scripts\scribeflow.exe')) -and (-not $force) -and (-not $env:SCRIBEFLOW_SOURCE)) {
  $remote = $null
  try {
    $txt = (Invoke-WebRequest -UseBasicParsing -TimeoutSec 20 -Uri 'https://raw.githubusercontent.com/KMC1525/ScribeFlow/main/scribeflow/__init__.py' -ErrorAction Stop).Content
    if ($txt -is [byte[]]) { $txt = [System.Text.Encoding]::UTF8.GetString($txt) }
    if ($txt -match "__version__\s*=\s*[`"']([0-9][0-9.]*)") { $remote = $Matches[1] }
  } catch { }
  try { if ($remote -and ([version]$remote -le [version]("$old".Trim()))) { $skip = $true } } catch { }
}
if ($skip) { Note (L "ScribeFlow $old já instalado e na versão mais recente — nada a baixar." "ScribeFlow $old already installed and up to date — nothing to download.") }
else {
  Note (L 'Baixando e instalando o ScribeFlow …' 'Downloading and installing ScribeFlow …')
  & $venvPy -m pip install --upgrade --disable-pip-version-check --quiet --no-cache-dir $req
  if ($LASTEXITCODE -ne 0) { Die (L 'Falha ao instalar. Verifique sua conexão e tente de novo.' 'Installation failed. Check your connection and try again.') }
}
$new = & $venvPy -I -c "import scribeflow; print(scribeflow.__version__)"

# 4) comandos `scribeflow` e `scribe`
# O atalho aponta para o .exe pelo caminho RELATIVO ao próprio arquivo (bin\..\app\venv): gravado em ASCII, um caminho absoluto com acento (C:\Users\João\…) quebraria o comando.
Set-Content -ErrorAction Stop -Path (Join-Path $BinDir 'scribeflow.cmd') -Value "@echo off`r`n`"%~dp0..\app\venv\Scripts\scribeflow.exe`" %*" -Encoding ASCII
Set-Content -ErrorAction Stop -Path (Join-Path $BinDir 'scribe.cmd') -Value "@echo off`r`n`"%~dp0..\app\venv\Scripts\scribe.exe`" %*" -Encoding ASCII

# 4b) o comando `scribeflow` no PATH — do usuário (para novos terminais) e deste terminal (para usar já). Feito ANTES das bibliotecas, que demoram.
$sf = Join-Path $venv 'Scripts\scribeflow.exe'
function Same-Dir($a, $b) { return ($a.TrimEnd('\') -ieq $b.TrimEnd('\')) }
# O Path do usuário no registro costuma ter entradas «%USERPROFILE%\…» (tipo REG_EXPAND_SZ). Ler com GetEnvironmentVariable e regravar trocava tudo pelo valor já expandido (e o tipo por REG_SZ): perdia as variáveis.
# Aqui o valor CRU é lido e só se acrescenta a pasta; devolve $null se ela já está lá.
function Merge-PathEntry($raw, $dir) {
  $parts = @(if ($raw) { "$raw" -split ';' | Where-Object { $_ } })
  foreach ($p in $parts) { if (Same-Dir ([Environment]::ExpandEnvironmentVariables($p)) $dir) { return $null } }
  return (($parts + $dir) -join ';')
}
function Add-UserPath($dir) {
  try {
    $key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Environment', $true)
    try {
      $raw = $key.GetValue('Path', '', [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
      $kind = [Microsoft.Win32.RegistryValueKind]::ExpandString
      try { $kind = $key.GetValueKind('Path') } catch { }
      $merged = Merge-PathEntry $raw $dir
      if ($null -eq $merged) { return $false }
      $key.SetValue('Path', $merged, $kind)
    } finally { $key.Close() }
    [Environment]::SetEnvironmentVariable('SCRIBEFLOW_PATH_REFRESH', $null, 'User')   # só para o Windows avisar os programas abertos de que o ambiente mudou
    return $true
  } catch {
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    $merged = Merge-PathEntry $userPath $dir
    if ($null -eq $merged) { return $false }
    [Environment]::SetEnvironmentVariable('Path', $merged, 'User')
    return $true
  }
}
if (Add-UserPath $BinDir) { Note (L 'Adicionei o comando ao seu PATH.' 'I added the command to your PATH.') }
if (-not (($env:Path -split ';') | Where-Object { $_ -and (Same-Dir $_ $BinDir) })) { $env:Path = $env:Path.TrimEnd(';') + ';' + $BinDir }   # vale já neste terminal (com `irm | iex`)

# 5) motor de IA local (llama.cpp). Um pacote pronto é tentado primeiro; compilar só se não houver (precisa do «Build Tools for Visual Studio» e do cmake).
$engineFailed = $false
$eng = if ($env:SCRIBEFLOW_ENGINE) { $env:SCRIBEFLOW_ENGINE.ToLower() } else { 'yes' }
$prevEap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'   # avisos do pip no stderr não podem abortar o instalador
if ($eng -in @('no', 'none', '0')) { Note (L "Motor de IA: pulado (SCRIBEFLOW_ENGINE=$eng)." "AI engine: skipped (SCRIBEFLOW_ENGINE=$eng).") }
else {
  Say (L 'Motor de IA local (llama.cpp) …' 'Local AI engine (llama.cpp) …')
  if ($eng -in @('cpu', 'cuda')) { & $sf engine install --backend $eng } else { & $sf engine install }
  if ($LASTEXITCODE -ne 0) { $engineFailed = $true }
}

# 6) modelo de texto padrão (Hugging Face). Sem $env:SCRIBEFLOW_MODEL, PERGUNTA no terminal antes de baixar.
$modelFailed = $false
$m = if ($env:SCRIBEFLOW_MODEL) { $env:SCRIBEFLOW_MODEL.ToLower() } else { 'ask' }
if ($m -eq 'ask') {
  $a = ''
  try { $a = Read-Host (L 'Baixar agora o modelo de texto padrão (darrellbest/Qwen3.5-2B-Heretic-GGUF, ~1,3 GB)? [S/n]' 'Download the default text model now (darrellbest/Qwen3.5-2B-Heretic-GGUF, ~1.3 GB)? [Y/n]') } catch { $a = 'n' }
  $m = if ("$a".Trim().ToLower() -in @('n', 'no', 'nao', 'não')) { 'no' } else { 'yes' }
}
if ($m -in @('yes', '1', 'all')) {
  Say (L 'Baixando o modelo de texto padrão …' 'Downloading the default text model …')
  & $sf models pull
  if ($LASTEXITCODE -ne 0) { $modelFailed = $true }
} else { Note (L 'Modelo: pulado. Baixe depois em Configurações → Modelo de texto (IA), ou:  scribeflow models pull' 'Model: skipped. Download it later in Settings → Text model (AI), or:  scribeflow models pull') }
$ErrorActionPreference = $prevEap

if (-not $old) { Say (L "✓ ScribeFlow $new instalado." "✓ ScribeFlow $new installed.") }
elseif ($old -eq $new) { Say (L "✓ ScribeFlow $new já estava atualizado." "✓ ScribeFlow $new was already up to date.") }
else { Say (L "✓ ScribeFlow atualizado: $old → $new." "✓ ScribeFlow updated: $old → $new.") }
if ($engineFailed) { Note (L '⚠ O motor de IA não foi instalado (veja acima). O editor já funciona; para tentar de novo:  scribeflow engine install' '⚠ The AI engine was not installed (see above). The editor already works; to try again:  scribeflow engine install') }
if ($modelFailed) { Note (L '⚠ O modelo não foi baixado (veja acima). Para tentar de novo:  scribeflow models pull' '⚠ The model was not downloaded (see above). To try again:  scribeflow models pull') }
Write-Host ''
if (Get-Command scribeflow -ErrorAction SilentlyContinue) { Note (L 'Para abrir o ScribeFlow:   scribeflow' 'To open ScribeFlow:   scribeflow') }
else {
  Note (L "Para abrir o ScribeFlow:   & '$sf'" "To open ScribeFlow:   & '$sf'")
  Note (L "O comando 'scribeflow' só será reconhecido em terminais NOVOS (feche e abra o PowerShell) ou, neste, depois de rodar o instalador com:  irm <endereço> | iex" "The 'scribeflow' command will only be recognized in NEW terminals (close and reopen PowerShell) or, in this one, after running the installer with:  irm <address> | iex")
}
Note (L 'Para atualizar:   rode este mesmo comando de novo (ou: scribeflow update)' 'To update:   run this same command again (or: scribeflow update)')
