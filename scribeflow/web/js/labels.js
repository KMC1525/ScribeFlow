// Rótulos usados com t(variável) nas telas (sem dependências do navegador: o teste de traduções lê este arquivo no Node).
export const SORTS = [['updated', 'Mais recentes'], ['name', 'Nome (A–Z)'], ['created', 'Mais antigos primeiro'], ['words', 'Mais palavras']];
export const SETTINGS_TABS = [['model', 'Modelo de texto (IA)'], ['editor', 'Editor'], ['appearance', 'Aparência'], ['advanced', 'Avançado']];
// Rótulos de qualidade das quantizações GGUF (a chave vem de scribeflow/hf.py: parse_quant).
export const QUALITY_LABEL = { very_low: 'Qualidade muito baixa', low: 'Qualidade baixa', good: 'Boa qualidade', very_good: 'Muito boa qualidade', high: 'Quase igual ao original', lossless: 'Praticamente sem perdas', original: 'Original (grande)' };
export const CTX_CHIPS = [[4096, '4K'], [8192, '8K'], [16384, '16K'], [32768, '32K'], [65536, '64K'], [131072, '128K']];
