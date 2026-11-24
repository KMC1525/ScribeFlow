// ScribeFlow → Editor: painel da esquerda com o SYSTEM PROMPT GERAL do projeto (no lugar dos lorebooks do Scriber do ASTA).
// Uma caixa de texto livre — estilo, voz, personagens, mundo, regras e o que a IA deve lembrar — que guia TODAS as ações da IA (melhorar, expandir, encurtar, reescrever, diálogo, ortografia…).
import { t } from '../i18n.js';
import { btn } from '../scriber_ui.js';
import { debounce, h, toast } from '../ui.js';

const MAX = 12000;
const TEMPLATE = () => [t('## Estilo e voz'), t('(ex.: terceira pessoa, passado, frases curtas, humor seco, sem advérbios em -mente)'), '',
  t('## Personagens'), t('(nome, idade, aparência, personalidade, como fala)'), '',
  t('## Mundo e contexto'), t('(lugares, época, regras do mundo, fatos que não podem ser contraditos)'), '',
  t('## O que evitar'), t('(clichês, termos proibidos, temas, formatos)'), ''].join('\n');

// devolve { el, value(), flush() }
export function createSystemPanel(S) {
  let saved = S.proj.system_prompt || '', pending = null;
  const ta = h('textarea', { id: 'sc-sys', maxlength: MAX, 'aria-label': t('System prompt geral'), spellcheck: 'false',
    placeholder: t('Escreva aqui as instruções gerais do texto: estilo e voz, personagens, mundo, regras e o que a IA deve lembrar. Todas as ações da IA seguem isto.') });
  ta.value = saved;
  const count = h('span', { class: 'dim small', id: 'sc-sys-count' });
  const state = h('span', { class: 'dim small', id: 'sc-sys-state' }, t('salvo'));
  const paint = () => { count.textContent = t('{c} caracteres · ≈ {k} tokens', { c: ta.value.length, k: Math.ceil(ta.value.length / 3) }); };
  async function doSave() {
    const v = ta.value;
    if (v === saved) { state.textContent = t('salvo'); return; }
    state.textContent = t('salvando…');
    try { S.proj = await S.api.put('', { system_prompt: v }); saved = S.proj.system_prompt; state.textContent = ta.value === saved ? t('salvo') : t('não salvo'); }
    catch (e) { state.textContent = t('não salvo'); toast(e.message, 'err'); }
  }
  const later = debounce(() => { pending = doSave(); }, 600);
  ta.addEventListener('input', () => { paint(); state.textContent = t('não salvo'); later(); });
  const flush = async () => { if (ta.value !== saved) pending = doSave(); if (pending) { try { await pending; } catch (e) { /* já avisou */ } } };
  S.onCleanup(() => { if (ta.value !== saved) doSave(); });

  const insert = btn(t('Inserir modelo'), 'plus', () => { ta.value = ta.value.trim() ? ta.value.replace(/\s*$/, '\n\n') + TEMPLATE() : TEMPLATE(); ta.focus(); paint(); later(); }, '', { id: 'sc-sys-tpl', title: t('Insere um esqueleto: estilo, personagens, mundo e o que evitar') });
  const imp = h('input', { type: 'file', accept: '.txt,.md,.markdown,text/plain', class: 'hidden', id: 'sc-sys-file' });
  imp.addEventListener('change', async () => {
    const f = imp.files[0]; imp.value = '';
    if (!f) return;
    if (f.size > 200000) { toast(t('Arquivo grande demais para um system prompt.'), 'err'); return; }
    const txt = (await f.text()).slice(0, MAX);
    ta.value = ta.value.trim() ? ta.value.replace(/\s*$/, '\n\n') + txt : txt; paint(); later();
  });
  const el = h('aside', { class: 'sc-left', id: 'sc-system', 'aria-label': t('System prompt geral') },
    h('div', { class: 'sc-ph' }, h('b', null, t('System prompt geral')), h('span', { class: 'grow' }), state),
    h('div', { class: 'sc-ftool' }, insert, btn(t('Importar'), 'upload', () => imp.click(), '', { id: 'sc-sys-imp', title: t('Carregar de um arquivo .txt ou .md') }), imp,
      btn(t('Limpar'), 'trash', () => { if (!ta.value) return; ta.value = ''; paint(); later(); }, 'ghost', { id: 'sc-sys-clear' })),
    h('div', { class: 'sc-sys-body' }, ta),
    h('div', { class: 'sc-lore-foot hint' }, count, h('div', null, t('A IA lê isto em toda ação (melhorar, expandir, encurtar, reescrever, diálogo, corrigir…). Fica salvo no projeto e vai junto na exportação em JSON.'))));
  paint();
  return { el, value: () => ta.value, flush };
}
