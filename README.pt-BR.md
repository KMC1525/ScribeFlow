<div align="center">

# ScribeFlow

**Um editor de textos com IA local — romances, reportagens, análises, copy e trabalhos acadêmicos — no navegador, com modelos de texto do Hugging Face.**

Escreva num editor parecido com o Word, selecione um parágrafo ou uma fala e deixe a IA melhorar, expandir, encurtar, reescrever ou corrigir só aquele trecho, guiada por um **system prompt geral** do texto inteiro. Tudo roda no seu computador. Sem contas, sem chaves de API, sem modelos na nuvem, sem telemetria.

[Instalar](#instalar) · [Usar](#usar) · [Modelo](#o-modelo-de-texto) · [Projetos](#projetos) · [Configurações](#configurações) · [Dados](#seus-dados) · [Desenvolvimento](#desenvolvimento) · [Changelog](CHANGELOG.md) · [English](README.md)

`MIT` · `Windows` · `macOS` · `Linux` · `Python 3.9+` · `v0.1.0`

</div>

---

O ScribeFlow é o **Scriber** do [ASTA](https://github.com/KMC1525/ASTA) transformado num app próprio (sem a aba *Geração automática*), com o sistema de projetos e as cores do [OpenFlow](https://github.com/KMC1525/OpenFlow): Python (só biblioteca padrão) + interface em HTML/CSS/JS puro, um comando `scribeflow` (atalho: `scribe`).

## Instalar

Um comando instala **e** atualiza (seus dados em `~/.scribeflow` nunca são tocados):

```bash
curl -fsSL https://raw.githubusercontent.com/KMC1525/ScribeFlow/main/install.sh | sh        # Linux / macOS
```

```powershell
irm https://raw.githubusercontent.com/KMC1525/ScribeFlow/main/install.ps1 | iex             # Windows
```

O instalador: acha (ou instala) o Python 3.9+, cria um ambiente isolado, instala o ScribeFlow, instala o **motor de IA local** (llama.cpp, pelo `llama-cpp-python`: um pacote pronto, quando existe; senão compila) e **pergunta** se quer baixar o modelo padrão (~1,3 GB). Depois:

```bash
scribeflow            # abre http://localhost:8791 no navegador
```

Variáveis úteis (todas opcionais): `SCRIBEFLOW_ENGINE=yes|no|cpu|cuda|metal` · `SCRIBEFLOW_MODEL=ask|yes|no` · `SCRIBEFLOW_PYTHON=auto|keep` · `SCRIBEFLOW_SOURCE=<url|pasta>` · `SCRIBEFLOW_FORCE=1` · `SCRIBEFLOW_LANG=pt|en`. Instalação manual: `pip install .` e depois `scribeflow engine install`.

> Sem o motor ou sem modelo o ScribeFlow continua funcionando: editor, corretor, estatísticas, histórico e exportação em `.docx`/`.md`/`.txt`/`.html`. Só as ações da IA (menos *Corrigir* e *Encurtar*, que têm um plano B por regras) precisam do modelo.

## Usar

1. **Projetos** (tela inicial): cada texto é um projeto — pesquise por título, descrição, system prompt ou *pelo próprio texto*, ordene, crie, duplique, apague, **importe/exporte em JSON**.
2. **Editor:** negrito/itálico/títulos/listas/alinhamento/quebra de página, localizar e substituir, histórico, zoom, formatação do papel (fonte, espaçamento, recuo, margens, página), corretor (navegador + regras + dicionário do sistema) e estatísticas.
3. **System prompt geral** (painel da esquerda): uma caixa de texto livre — estilo e voz, personagens, mundo, regras, o que evitar. **Toda ação da IA segue isto.**
4. **Ações da IA** (painel da direita, ou a barra flutuante sobre a seleção): *Melhorar · Expandir · Reescrever · Encurtar · Corrigir · Continuar · Virar diálogo · Descrever mais · Mudar o tom · Traduzir · Pedir…*, com tamanho escolhido para a expansão (parágrafos e falas separados). Selecione livremente ou ligue os modos de clique *Parágrafo* / *Fala*. Aceite, tente de novo ou descarte — e o Ctrl+Z desfaz.
5. **Revisão:** regras + dicionário do sistema, ou *Revisar com IA* (gramática e concordância; cada correção é conferida contra o texto real antes de aparecer).
6. **Web** (opcional, desligada por padrão): pesquisa no DuckDuckGo/Wikipédia, lê uma página e fixa como fonte para a IA. É a única coisa, além do Hugging Face, que acessa a internet.

## O modelo de texto

O ScribeFlow usa **somente modelos de geração de texto do Hugging Face**, em GGUF, rodando localmente. Não há provedores de nuvem nem «frontier».

- **Modelo padrão:** [`darrellbest/Qwen3.5-2B-Heretic-GGUF`](https://huggingface.co/darrellbest/Qwen3.5-2B-Heretic-GGUF) (`Q4_K_M`, ~1,3 GB), com **janela de contexto de 16K tokens**.
- **Configurações → Modelo de texto (IA):** modelo em uso, *testar*, **janela de contexto** (4K … 128K, ou qualquer número), modelos baixados (usar / apagar) e uma **barra de pesquisa** que busca modelos de texto no Hugging Face (por nome, autor como `unsloth`, `dono/nome` ou o endereço da página), lista as quantizações de cada repositório (a recomendada para a sua RAM vem marcada) e **baixa direto de lá**, com progresso, retomada e conferência do arquivo. Repositórios de imagem, vídeo, voz e embeddings são recusados.
- Terminal: `scribeflow models search qwen` · `models pull [dono/nome] [--file Q4_K_M]` · `models list|use|rm`.
- Repositórios multimodais (como o padrão, marcado `image-text-to-text`) funcionam: só a parte de texto é usada e o arquivo `mmproj` nunca é oferecido.

## Projetos

O mesmo sistema do OpenFlow: uma pasta por projeto em `~/.scribeflow/projects/<id>/` (`project.json`, `document.json`, `history/`, `exports/`). **Exportar / importar em JSON** (menu do cartão, ou o menu do editor): um arquivo com o texto, o system prompt, a formatação, as fontes fixadas e o histórico. Importar sempre cria um projeto **novo** e revalida tudo (nunca sobrescreve). Terminal: `scribeflow projects list|export ID -o arquivo.json|import arquivo.json`.

## Configurações

| Aba | O quê |
|---|---|
| **Modelo de texto (IA)** | modelo em uso, janela de contexto, modelos baixados, pesquisa e download no Hugging Face |
| **Editor** | tipo/idioma/conteúdo padrão, tamanhos da expansão, salvamento automático, corretor, tamanho do histórico |
| **Aparência** | tema (escuro/claro/auto), cor de destaque, tamanho da interface, densidade, fonte, idioma |
| **Avançado** | camadas na GPU, threads, descarregar parado, modelos que «pensam» ligado/desligado, token do Hugging Face, pasta dos modelos, busca na web, exportar/importar configurações |

O token do Hugging Face fica só no seu computador e nunca é enviado ao navegador.

## Seus dados

Tudo são arquivos comuns em `~/.scribeflow` (troque com `SCRIBEFLOW_HOME`): `settings.json`, `projects/`, `models/`. Atualizar ou desinstalar nunca os apaga. O servidor escuta só em `127.0.0.1` (e confere `Host`/`Origin`); o texto vindo do navegador, da IA e de arquivos importados é validado pelo modelo de blocos antes de ser guardado. Sem telemetria.

## Desenvolvimento

```bash
python -m unittest discover -s tests -t .      # testes de Python (+ navegador, se houver Node + Playwright)
node tests/js/i18n_check.mjs                  # toda frase da interface tem tradução para o inglês
```

Estrutura: `scribeflow/` — `server.py` (HTTP + SSE), `projects.py` (projetos), `hf.py`/`dl.py` (busca e downloads rápidos e retomáveis), `llm.py` (modelo local), `ai.py` + `prompts/` (ações do editor), `docmodel.py`/`docx.py`/`spell.py`/`stats.py` (o documento), `web/` (interface, sem etapa de build). Veja [AGENTS.md](AGENTS.md) e [CONTRIBUTING.pt-BR.md](CONTRIBUTING.pt-BR.md).

### O que não foi verificado (leia)

- **Não rodei uma geração de verdade com o modelo padrão.** O Hugging Face estava inacessível no ambiente onde isto foi construído, então o modelo nunca foi baixado e o `llama-cpp-python` nunca foi compilado nem executado lá. A busca, a lista de arquivos e o download foram testados contra um servidor falso local que imita a API do Hub (o formato foi conferido contra o repositório padrão real pelo conector do Hugging Face); as chamadas ao modelo foram testadas com um substituto do `llama_cpp`. Se o `llama-cpp-python` que você instalar suporta a arquitetura `qwen3.5` depende do llama.cpp embutido nele — se o carregamento falhar, rode `scribeflow engine install --upgrade`.
- **Só o Linux foi executado.** Os instaladores e toda a suíte estão no CI para Linux, macOS e Windows, mas o `install.ps1` nunca foi executado (não há PowerShell aqui) e os caminhos de Windows/macOS não foram testados.
- O índice de pacotes prontos do `llama-cpp-python` não pôde ser acessado, então o caminho «pacote pronto primeiro, compilar se faltar» não foi exercitado; compilar exige compilador C/C++ e cmake.
- A busca na web (DuckDuckGo/Wikipédia) não foi exercitada nos sites reais.
