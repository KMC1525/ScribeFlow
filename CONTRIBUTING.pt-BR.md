# Contribuindo com o ScribeFlow

Obrigado por ajudar! Um guia curto (a [versão em inglês](CONTRIBUTING.md) diz o mesmo).

- **Rode os testes** antes de abrir um pull request: `python -m unittest discover -s tests -t .` (o teste em Chromium roda quando há Node + Playwright; aponte `NODE_PATH` para o `node_modules` que tem o Playwright) e `node tests/js/i18n_check.mjs`.
- **Python ≥ 3.9**, só biblioteca padrão no núcleo (extras ficam em `pyproject.toml`). Sem `match`, sem `X | Y` em tempo de execução.
- **Só modelos de texto locais do Hugging Face.** Sem provedores de nuvem nem chaves de API de modelos.
- **Textos:** a interface e o terminal são em português com tradução para o inglês (`scribeflow/web/js/en.js`, `L("pt", "en")` no `cli.py`, os instaladores usam `L "pt" "en"`). Uma frase nova sem tradução faz o `tests/test_misc.py` falhar.
- **Documentação:** quando comportamento, instalação, comandos ou limites mudam, atualize `README.md` + `README.pt-BR.md` e `CHANGELOG.md` + `CHANGELOG.en.md` (por versão: o que mudou e, com honestidade, o que não foi verificado).
- **Segurança:** trate arquivos, JSON importado, URLs e a saída da IA como não confiáveis (valide caminhos, tamanhos, tipos, JSON). A IA produz texto (ou dados que o código valida), nunca código para executar.
- Correções de bugs vêm com um teste que reproduz o erro. Nunca afirme na documentação o que não foi testado.
