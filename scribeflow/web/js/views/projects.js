import { api } from '../api.js';
import { t } from '../i18n.js';
import { openProject, state } from '../main.js';
import { SORTS } from '../labels.js';
import { GROUP_LABEL, catalog, labeled } from '../scriber_ui.js';
import { confirmDialog, debounce, fill, fmtDate, h, icon, modal, popover, select, toast } from '../ui.js';

// Tela inicial do ScribeFlow: todos os projetos (o mesmo sistema do OpenFlow), com barra de pesquisa (nome, descrição, system prompt e texto), ordenação, criação e importação/exportação em JSON.
const SORT_KEY = 'scribeflow.pj.sort';

export default async function render(root, ctx) {
  let sort = 'updated';
  try { sort = SORTS.some(([v]) => v === localStorage.getItem(SORT_KEY)) ? localStorage.getItem(SORT_KEY) : 'updated'; } catch (e) { /* ok */ }
  let list = [], total = 0, query = '', seq = 0;
  const cat = await catalog();
  const grid = h('div', { class: 'cv-grid', role: 'list', 'aria-label': t('Projetos') });
  const status = h('p', { class: 'muted small pj-status', role: 'status', 'aria-live': 'polite' });
  const empty = h('div', { class: 'empty' });

  async function create(opts = {}) {
    const sc = (state.settings || {}).scriber || {};
    const nw = { type: opts.type || sc.type || 'romance', language: sc.language || 'pt-BR' };
    const name = h('input', { placeholder: t('Título do projeto'), 'aria-label': t('Título do projeto'), id: 'pj-new-name', value: opts.name || '', maxlength: 100 });
    const typeSel = h('select', { id: 'pj-new-type', 'aria-label': t('Tipo de escrita') }, ['fiction', 'professional', 'academic'].map((g) => h('optgroup', { label: t(GROUP_LABEL[g]) },
      Object.entries(cat.types).filter(([, v]) => v.group === g).map(([k, v]) => h('option', { value: k, selected: k === nw.type }, t(v.label))))));
    typeSel.value = nw.type;
    const hint = h('div', { class: 'muted small', id: 'pj-new-hint' }, t(cat.types[nw.type].hint));
    typeSel.addEventListener('change', () => { nw.type = typeSel.value; hint.textContent = t(cat.types[nw.type].hint); });
    const langSel = select(Object.entries(cat.languages).map(([k, v]) => [k, t(v)]), nw.language, (v) => { nw.language = v; }, { id: 'pj-new-lang', 'aria-label': t('Idioma') });
    const desc = h('input', { placeholder: t('Descrição (opcional)'), 'aria-label': t('Descrição'), maxlength: 400, id: 'pj-new-desc' });
    const sys = h('textarea', { placeholder: t('System prompt geral (opcional): estilo, voz, personagens, regras… A IA segue isto em todas as ações. Dá para escrever depois.'), 'aria-label': t('System prompt geral'), rows: 3, id: 'pj-new-sys', style: { minHeight: '70px' } });
    const body = h('div', { class: 'sf-new' }, h('p', { class: 'muted small', style: { margin: 0 } }, t('Um projeto é um texto: um romance, uma reportagem, um artigo… com o seu system prompt geral, formatação e histórico. Crie um para cada ideia.')),
      name, h('div', { class: 'grid2' }, labeled(t('Tipo de escrita'), typeSel), labeled(t('Idioma'), langSel)), hint, desc, sys);
    const ok = await modal(t('Novo projeto'), body, [{ label: t('Cancelar'), value: false }, { label: t('Criar'), value: true, cls: 'primary' }]);
    if (!ok) return;
    try { const c = await api('/api/projects', { method: 'POST', body: { name: name.value.trim(), type: nw.type, language: nw.language, description: desc.value.trim(), system_prompt: sys.value } }); openProject(c.id); }
    catch (e) { toast(e.message, 'err'); }
  }

  async function load() {
    const my = ++seq;
    try {
      const r = await api('/api/projects?sort=' + sort + (query ? '&q=' + encodeURIComponent(query) : ''));
      if (my !== seq) return;   // chegou uma resposta mais nova (digitou mais uma letra): ignora a antiga
      list = r;
      if (!query) total = r.length;
      else if (!total) total = (await api('/api/projects')).length;
    } catch (e) { if (my === seq) toast(e.message, 'err'); return; }
    paint();
  }
  const reload = () => load();

  function downloadJson(c) { const a = h('a', { href: `/api/projects/${c.id}/export.json`, download: c.id + '.scribeflow.json', class: 'hidden' }); document.body.appendChild(a); a.click(); a.remove(); toast(t('Projeto exportado em JSON.'), 'ok'); }

  function menu(anchor, c) {
    const item = (label, ic, fn, cls) => h('button', { type: 'button', class: 'opt ' + (cls || ''), role: 'menuitem', onclick: () => { pop.close(); fn(); } }, icon(ic, 15), label);
    const pop = popover(anchor, h('div', { role: 'menu' },
      item(t('Abrir'), 'doc', () => openProject(c.id)),
      item(t('Renomear'), 'edit', async () => {
        const inp = h('input', { value: c.name, 'aria-label': t('Título do projeto'), maxlength: 100 });
        const ok = await modal(t('Renomear projeto'), inp, [{ label: t('Cancelar'), value: false }, { label: t('Salvar'), value: true, cls: 'primary' }]);
        if (ok && inp.value.trim()) { await api(`/api/projects/${c.id}`, { method: 'PUT', body: { name: inp.value } }); reload(); }
      }),
      item(t('Duplicar'), 'copy', async () => { await api(`/api/projects/${c.id}/duplicate`, { method: 'POST', body: {} }); toast(t('Duplicado')); reload(); }),
      item(t('Exportar projeto (JSON)'), 'download', () => downloadJson(c)),
      item(t('Apagar'), 'trash', async () => {
        if (!(await confirmDialog(t('Apagar o projeto “{n}” e todos os arquivos dele? Isso não pode ser desfeito.', { n: c.name })))) return;
        try { await api('/api/projects/' + c.id, { method: 'DELETE' }); toast(t('Apagado')); reload(); } catch (e) { toast(e.message, 'err'); }
      }, 'danger')));
  }

  // trecho do nome com a pesquisa em destaque
  function mark(textValue) {
    const tokens = fold(query).split(/\s+/).filter(Boolean);
    if (!tokens.length) return textValue;
    const f = fold(textValue);
    const spans = [];
    tokens.forEach((tk) => { let i = f.indexOf(tk); while (i >= 0) { spans.push([i, i + tk.length]); i = f.indexOf(tk, i + tk.length); } });
    if (!spans.length) return textValue;
    spans.sort((a, b) => a[0] - b[0]);
    const merged = [spans[0].slice()];
    spans.slice(1).forEach((s) => { const l = merged[merged.length - 1]; if (s[0] <= l[1]) l[1] = Math.max(l[1], s[1]); else merged.push(s.slice()); });
    const out = []; let at = 0;
    merged.forEach(([a, b]) => { if (a > at) out.push(textValue.slice(at, a)); out.push(h('mark', null, textValue.slice(a, b))); at = b; });
    if (at < textValue.length) out.push(textValue.slice(at));
    return out;
  }
  // a pesquisa ignora acentos; o texto exibido mantém o comprimento (NFD só em letras simples)
  function fold(s) { return String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase(); }

  function paint() {
    fill(grid, list.map((c) => h('div', { class: 'cv-card', role: 'listitem', dataset: { pid: c.id } },
      h('a', { class: 'cv-open', href: '#/project/' + c.id, onclick: () => { state.ctx = {}; } },
        h('div', { class: 'th doc' }, h('span', { class: 'ex' }, c.excerpt || t('Texto vazio: abra e comece a escrever.')), h('span', { class: 'ic' }, icon('doc', 28))),
        h('div', { class: 'inf' }, h('div', { class: 'nm', title: c.name }, mark(c.name)),
          c.match ? h('div', { class: 'mt match' }, t('Achado em:') + ' ', h('em', null, mark(c.match))) : (c.description ? h('div', { class: 'mt dsc' }, c.description) : null),
          h('div', { class: 'mt' }, t((cat.types[c.type] || { label: c.type }).label) + ' · ' + t('{w} palavras · {p} páginas', { w: c.words, p: c.pages }) + ' · ' + fmtDate(c.updated)))),
      h('button', { class: 'btn icon sm mn', type: 'button', title: t('Mais'), 'aria-label': t('Mais ações para {n}', { n: c.name }), 'aria-haspopup': 'menu', onclick: (e) => { e.stopPropagation(); menu(e.currentTarget, c); } }, icon('more', 15)))));
    const none = !list.length;
    grid.classList.toggle('hidden', none);
    empty.classList.toggle('hidden', !none);
    if (none) {
      if (query) fill(empty, h('h3', { role: 'heading', 'aria-level': '2' }, t('Nenhum projeto encontrado para “{q}”', { q: query })), h('p', null, t('A pesquisa olha o título, a descrição, o system prompt e o texto dos projetos.')),
        h('div', { class: 'row', style: { justifyContent: 'center' } }, h('button', { class: 'btn', type: 'button', onclick: () => { input.value = ''; query = ''; input.focus(); load(); } }, t('Limpar pesquisa')),
          h('button', { class: 'btn primary', type: 'button', onclick: () => create({ name: query }) }, icon('plus', 14), t('Criar um projeto chamado “{q}”', { q: query }))));
      else fill(empty, h('h3', { role: 'heading', 'aria-level': '2' }, t('Crie seu primeiro projeto')), h('p', null, t('Escreva romances, reportagens, análises, copy, trabalhos acadêmicos… com uma IA local que segue o seu system prompt geral. Tudo fica em arquivos na sua pasta.')),
        h('button', { class: 'btn primary', type: 'button', onclick: () => create() }, icon('plus', 14), t('Novo projeto')));
    }
    status.textContent = query ? (list.length ? t('{n} de {m} projetos', { n: list.length, m: total }) : t('Nenhum projeto encontrado.')) : (total ? t('{n} projetos', { n: total }) : '');
  }

  const importIn = h('input', { type: 'file', accept: '.json,application/json', class: 'hidden', id: 'pj-import-file', 'aria-label': t('Importar projeto (JSON)'), onchange: async (e) => {
    const f = e.target.files[0]; e.target.value = '';
    if (!f) return;
    try { const c = await api('/api/projects/import', { method: 'POST', body: f, raw: true, headers: { 'Content-Type': 'application/json' } }); toast(t('Projeto importado'), 'ok'); openProject(c.id); } catch (err) { toast(err.message, 'err'); }
  } });
  const input = h('input', { type: 'search', id: 'pj-search', placeholder: t('Pesquisar projetos…'), 'aria-label': t('Pesquisar projetos'), autocomplete: 'off', spellcheck: 'false',
    oninput: debounce(() => { query = input.value.trim(); load(); }, 180),
    onkeydown: (e) => { if (e.key === 'Escape' && input.value) { e.preventDefault(); input.value = ''; query = ''; load(); } else if (e.key === 'Enter') { e.preventDefault(); query = input.value.trim(); load(); } } });
  const sortSel = h('select', { id: 'pj-sort', 'aria-label': t('Ordenar por'), onchange: (e) => { sort = e.target.value; try { localStorage.setItem(SORT_KEY, sort); } catch (x) { /* ok */ } load(); } },
    SORTS.map(([v, l]) => h('option', { value: v, selected: v === sort }, t(l))));

  fill(root, h('div', { class: 'page cv-pg' },
    h('div', { class: 'page-h' }, h('div', null, h('h1', null, t('Projetos')), h('p', null, t('Todos os seus textos: romances, reportagens, análises, copy, trabalhos acadêmicos e mais — escritos e editados com uma IA local.'))),
      h('div', { class: 'row' }, h('button', { class: 'btn', type: 'button', id: 'pj-import', onclick: () => importIn.click() }, icon('upload', 14), t('Importar projeto (JSON)')), importIn, h('button', { class: 'btn primary', type: 'button', id: 'pj-new', onclick: () => create() }, icon('plus', 14), t('Novo projeto')))),
    h('form', { class: 'pj-bar', role: 'search', onsubmit: (e) => e.preventDefault() },
      h('div', { class: 'search' }, icon('search', 17), input, h('span', { class: 'kbd', 'aria-hidden': 'true' }, '/')), h('label', { class: 'pj-sort' }, h('span', { class: 'dim small' }, t('Ordenar por')), sortSel)),
    status, grid, empty));
  await load();
  if (ctx && ctx.create) { state.ctx = {}; create(); }
}
