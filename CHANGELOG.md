# Changelog

Formato: `## [versão] — data`. Cada versão lista o que mudou para quem usa e, com honestidade, o que **não** foi verificado. [English](CHANGELOG.en.md)

## [0.1.0] — 2026-11-24

Primeira versão. O ScribeFlow é o **Scriber** do ASTA como app próprio, com o sistema de projetos e as cores do OpenFlow e um modelo de texto local do Hugging Face.

### Novo
- **App web e comando `scribeflow`** (atalho `scribe`), Windows · macOS · Linux, instalado pelo terminal (`install.sh` / `install.ps1`, que também atualizam).
- **Editor do Scriber do ASTA, sem a aba *Geração automática*:** editor parecido com o Word, formatação do papel, localizar e substituir, histórico, corretor (regras + dicionário do sistema + navegador), revisão com IA, estatísticas do texto, pesquisa na web/fontes fixadas, exportação e importação em `.docx`/`.md`/`.txt`/`.html`.
- **System prompt geral** no lugar dos lorebooks: uma caixa de texto por projeto que guia **toda** ação da IA (melhorar, expandir, reescrever, encurtar, corrigir, continuar, diálogo, descrever, tom, traduzir, pedir…) e a revisão com IA. Fica salvo no projeto.
- **Projetos como no OpenFlow:** uma pasta por projeto, tela inicial com pesquisa (título, descrição, system prompt e o texto), ordenação, criar/renomear/duplicar/apagar.
- **Exportar / importar projetos em JSON** (interface e `scribeflow projects export|import`): texto, system prompt, formatação, fontes fixadas e histórico. Importar sempre cria um projeto novo e revalida tudo.
- **Só modelos de texto locais do Hugging Face (GGUF).** Não existem provedores de nuvem nem «frontier». Modelo padrão: `darrellbest/Qwen3.5-2B-Heretic-GGUF` (Q4_K_M) com **janela de contexto de 16K tokens**.
- **Configurações → Modelo de texto (IA):** trocar o modelo, ajustar a janela de contexto (4K…128K ou qualquer valor), testar, e uma **barra de pesquisa** que busca modelos de geração de texto no Hugging Face e **baixa direto** (escolha da quantização com a recomendada para a RAM marcada, download paralelo com retomada, conferência do GGUF, cancelar). Repositórios que não são de texto são recusados; arquivos `mmproj` nunca são oferecidos.
- Configurações do editor, da aparência (mesma paleta do OpenFlow, claro/escuro/auto, escala, fontes) e avançadas (camadas na GPU, threads, descarregar parado, modelos que «pensam», token do Hugging Face, pasta dos modelos, busca na web, exportar/importar configurações).
- Terminal: `scribeflow models list|search|pull|use|rm`, `engine status|install`, `projects list|export|import`, `update`, `folder`, `doctor`, `version`.
- Interface em português com tradução para o inglês (conferida por `node tests/js/i18n_check.mjs`).

### Tirado do Scriber (de propósito)
- A aba **Geração automática** (e a API dela: planejar → escrever → revisar → empacotar).
- Os **lorebooks** (trocados pelo system prompt geral).
- O seletor de equipe de agentes / esforço (era um recurso do ASTA inteiro; o ScribeFlow roda um único modelo local pequeno).
- Os anexos no prompt (só serviam à geração automática).

### Não verificado
- **Nenhuma geração de verdade foi executada.** O Hugging Face estava bloqueado no ambiente de construção: o modelo padrão nunca foi baixado e o `llama-cpp-python` nunca foi compilado nem executado lá. Download/busca/lista foram testados contra um Hub falso local; as chamadas ao modelo, contra um substituto do `llama_cpp` (incluindo o prompt com o «pensar» desligado). O suporte à arquitetura `qwen3.5` depende do llama.cpp embutido no `llama-cpp-python` que você instalar (`scribeflow engine install --upgrade`).
- **Só o Linux foi executado** (35+ testes de Python, um teste em Chromium da interface inteira e o `install.sh` de verdade numa pasta temporária). O `install.ps1` nunca foi executado; macOS e Windows só estão cobertos pela configuração do CI, que ainda não rodou.
- O índice de pacotes prontos do `llama-cpp-python` estava inacessível; o plano B de compilar exige compilador C/C++ e cmake.
- A busca na web do DuckDuckGo/Wikipédia não foi exercitada nos sites reais.
