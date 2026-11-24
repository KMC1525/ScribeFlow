import { api, events } from '../api.js';
import { t } from '../i18n.js';
import { go, refreshModel, refreshState, saveSettings, state } from '../main.js';
import { accentSwatches, themeCards } from '../appearance.js';
import { ui } from '../prefs.js';
import { CTX_CHIPS, QUALITY_LABEL, SETTINGS_TABS } from '../labels.js';
import { catalog } from '../scriber_ui.js';
import { checkbox, confirmDialog, field, fmtBytes, fmtEta, h, icon, select, seg, toast } from '../ui.js';

// Configurações do ScribeFlow: modelo de texto (trocar, pesquisar e baixar do Hugging Face, janela de contexto), editor, aparência e avançado.
const TABS = SETTINGS_TABS;

export default async function render(root, ctx) {
  let tab = TABS.some(([id]) => id === ctx.tab) ? ctx.tab : 'model';
  const body = h('div'), tabs = h('div', { class: 'tabs cfgtabs', role: 'tablist', 'aria-label': t('Configurações') });
  const FNS = { model: modelTab, editor: editorTab, appearance, advanced: advancedTab };
  const paintTabs = () => tabs.replaceChildren(...TABS.map(([id, l]) => h('button', { class: tab === id ? 'on' : '', role: 'tab', 'aria-selected': tab === id ? 'true' : 'false', dataset: { tab: id }, onclick: () => { tab = id; paintTabs(); paintBody(); } }, t(l))));
  const paintBody = async () => { body.replaceChildren(h('div', { class: 'spinner' })); body.replaceChildren(await (FNS[tab] || modelTab)(ctx)); };
  root.replaceChildren(h('div', { class: 'page narrow cfg' }, h('div', { class: 'page-h' }, h('div', null, h('h1', null, t('Configurações')), h('p', null, t('O modelo de texto (IA), o editor, a aparência e o avançado: configure uma vez e use em todos os projetos.')))), tabs, body));
  paintTabs(); await paintBody();
}

const cfgCard = (title, ...kids) => h('div', { class: 'card', style: { marginBottom: '16px' } }, title ? h('h3', { role: 'heading', 'aria-level': '2' }, title) : null, ...kids);   // a página só tem o h1; o título de cada cartão é de nível 2
const saveRow = (fn) => h('div', { class: 'row', style: { justifyContent: 'flex-end' } }, h('button', { class: 'btn primary', type: 'button', id: 'cfg-save', onclick: async () => { try { await fn(); toast(t('Salvo'), 'ok'); } catch (e) { toast(e.message, 'err'); } } }, icon('check', 15), t('Salvar')));
const numInput = (obj, key, min, max, step) => h('input', { type: 'number', min, max, step: step || 1, value: obj[key], oninput: (e) => { const v = parseFloat(e.target.value); if (!Number.isNaN(v)) obj[key] = v; } });
const fmtCtx = (n) => (n >= 1024 && n % 1024 === 0 ? (n / 1024) + 'K' : String(n));

// ===================================================================================== MODELO DE TEXTO (IA)
async function modelTab(ctx) {
  let M = await api('/api/models');
  const box = h('div', { id: 'cfg-model' });
  const dl = new Map();   // downloads em andamento: chave «repo|arquivo» → { done, total, speed, stop, jid }
  let filesFor = '';      // repositório com as opções de arquivo abertas
  let found = null;       // resultado da última pesquisa

  const reload = async () => { M = await refreshModel(); paint(); };
  const paint = () => box.replaceChildren(activeCard(), ctxCard(), installedCard(), searchCard());

  // ---------------------------------------------------------------- modelo em uso
  function activeCard() {
    const eng = M.engine || {}, act = M.local.find((m) => m.active);
    const kids = [];
    if (!eng.installed) kids.push(h('div', { class: 'errbox', id: 'cfg-engine-missing', style: { marginTop: 0, whiteSpace: 'normal' } }, t('O motor de IA local (llama.cpp) não está instalado. Rode no terminal:') + ' ', h('code', null, 'scribeflow engine install'), ' ' + t('e reinicie o ScribeFlow.')));
    if (!M.local.length) {
      const d = M.default || {};
      const running = dl.get(d.repo + '|' + d.file);
      kids.push(h('div', { class: 'sf-default', id: 'cfg-default' }, h('div', null, h('b', null, t('Nenhum modelo baixado ainda.')), h('div', { class: 'muted small' }, t('O modelo padrão do ScribeFlow é {r} ({f}).', { r: d.repo, f: d.file }))),
        h('button', { class: 'btn primary', type: 'button', id: 'cfg-pull-default', disabled: !!running, onclick: () => pullDefault() }, icon('download', 15), t('Baixar o modelo padrão'))));
    } else {
      kids.push(h('div', { class: 'sf-active', id: 'cfg-active' }, h('div', { class: 'grow' }, h('div', { class: 'nm' }, act ? act.name : t('(nenhum selecionado)')), h('div', { class: 'muted small' }, act ? [fmtBytes(act.size), act.quant, act.repo].filter(Boolean).join(' · ') : '')),
        h('span', { class: 'chip ' + (M.loaded ? 'on' : '') }, M.loaded ? t('carregado na memória') : t('não carregado')),
        h('button', { class: 'btn sm', type: 'button', id: 'cfg-test', onclick: testModel }, icon('play', 13), t('Testar')),
        M.loaded ? h('button', { class: 'btn sm', type: 'button', onclick: async () => { await api('/api/models/unload', { method: 'POST', body: {} }); toast(t('Modelo descarregado da memória.'), 'ok'); reload(); } }, t('Descarregar')) : null));
    }
    kids.push(h('div', { class: 'muted small', style: { marginTop: '8px' } }, eng.installed ? t('Motor: llama-cpp-python {v} · {g}', { v: eng.version || '?', g: eng.gpu ? t('com suporte a GPU') : t('só CPU') }) : ''));
    return cfgCard(t('Modelo em uso'), ...kids);
  }
  async function testModel() {
    const btn = document.getElementById('cfg-test'); if (btn) btn.disabled = true;
    toast(t('Testando… (a primeira vez carrega o modelo na memória e pode demorar)'));
    try { const r = await api('/api/models/test', { method: 'POST', body: {} }); toast(t('Funcionou: «{r}» em {s} s ({m}).', { r: r.reply, s: (r.ms / 1000).toFixed(1), m: r.model }), 'ok'); reload(); }
    catch (e) { toast(e.message, 'err'); } finally { if (btn) btn.disabled = false; }
  }

  // ---------------------------------------------------------------- janela de contexto
  function ctxCard() {
    const cur = state.settings.model.n_ctx, def = 16384;
    const inp = h('input', { type: 'number', id: 'cfg-nctx', min: 512, max: 1048576, step: 1024, value: cur, 'aria-label': t('Janela de contexto (tokens)') });
    const info = h('div', { class: 'muted small', id: 'cfg-nctx-info' });
    const showInfo = () => { const n = parseInt(inp.value || '0', 10) || 0; info.textContent = t('Usando {n} tokens de contexto (≈ {w} palavras entre o seu texto, o system prompt e a resposta).', { n: n.toLocaleString(), w: Math.round(n * 0.7).toLocaleString() }) + (n > 65536 ? ' ⚠ ' + t('Janelas grandes usam muita memória (RAM/VRAM) e deixam a geração mais lenta.') : ''); };
    const save = async (v) => { v = Math.max(512, Math.min(1048576, Math.round(v))); inp.value = v; showInfo(); await saveSettings({ model: { n_ctx: v } }); toast(t('Janela de contexto: {n} tokens.', { n: v.toLocaleString() }), 'ok'); chips(); };
    const chipsBox = h('div', { class: 'sc-chips', id: 'cfg-nctx-chips' });
    const chips = () => chipsBox.replaceChildren(...CTX_CHIPS.map(([n, l]) => h('button', { type: 'button', class: 'chip' + (state.settings.model.n_ctx === n ? ' on' : ''), dataset: { n }, onclick: () => save(n) }, l)));
    inp.addEventListener('change', () => { const v = parseFloat(inp.value); if (v > 0) save(v); });
    inp.addEventListener('input', showInfo);
    chips(); showInfo();
    return cfgCard(t('Janela de contexto'),
      field(t('Tamanho da janela (tokens)'), h('div', null, h('div', { class: 'row nw' }, inp, h('button', { class: 'btn sm', type: 'button', id: 'cfg-nctx-default', onclick: () => save(def) }, t('Padrão (16K)'))), chipsBox, info),
        t('Quanto texto o modelo enxerga de uma vez. O padrão é 16K tokens. Mudar recarrega o modelo na próxima ação da IA.')));
  }

  // ---------------------------------------------------------------- modelos baixados
  function installedCard() {
    const rows = M.local.map((m) => h('div', { class: 'sf-model' + (m.active ? ' on' : ''), dataset: { model: m.name } },
      h('div', { class: 'grow' }, h('div', { class: 'nm', title: m.name }, m.name), h('div', { class: 'muted small' }, [fmtBytes(m.size), m.quant && (m.quant + (m.quality ? ' · ' + t(QUALITY_LABEL[m.quality] || m.quality) : '')), m.repo].filter(Boolean).join(' · '))),
      m.active ? h('span', { class: 'chip on' }, t('em uso')) : h('button', { class: 'btn sm', type: 'button', dataset: { act: 'use' }, onclick: async () => { try { await api('/api/models/use', { method: 'POST', body: { name: m.name } }); toast(t('Modelo em uso: {n}', { n: m.name }), 'ok'); reload(); } catch (e) { toast(e.message, 'err'); } } }, t('Usar')),
      h('button', { class: 'btn ghost icon sm', type: 'button', title: t('Apagar o modelo do disco'), 'aria-label': t('Apagar o modelo do disco'), dataset: { act: 'delete' }, onclick: async () => {
        if (!(await confirmDialog(t('Apagar o modelo «{n}» do disco? Dá para baixar de novo depois.', { n: m.name })))) return;
        try { await fetch('/api/models/local/' + encodeURIComponent(m.name), { method: 'DELETE' }).then((r) => { if (!r.ok) throw new Error('Erro ' + r.status); }); toast(t('Apagado'), 'ok'); reload(); } catch (e) { toast(e.message, 'err'); } } }, icon('trash', 14))));
    return cfgCard(t('Modelos baixados'), M.local.length ? h('div', { class: 'sf-models', id: 'cfg-installed' }, rows) : h('p', { class: 'muted', style: { margin: 0 } }, t('Nada baixado ainda.')),
      h('p', { class: 'hint small', style: { marginBottom: 0 } }, t('Pasta dos modelos: {d}', { d: M.models_dir })));
  }

  // ---------------------------------------------------------------- pesquisar e baixar do Hugging Face
  const searchBox = h('div', { id: 'cfg-results' });
  const qIn = h('input', { type: 'search', id: 'cfg-hf-q', placeholder: t('Pesquisar modelos de texto no Hugging Face… (ex.: qwen, llama, gemma, unsloth)'), 'aria-label': t('Pesquisar modelos no Hugging Face'), autocomplete: 'off', spellcheck: 'false' });
  qIn.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); search(); } });
  function searchCard() {
    return cfgCard(t('Trocar o modelo: pesquisar no Hugging Face'),
      h('p', { class: 'muted small', style: { marginTop: 0 } }, t('Só modelos de geração de texto em GGUF. Pesquise pelo nome, por um autor (ex.: unsloth, bartowski) ou cole «dono/nome» ou o endereço da página do modelo.')),
      h('div', { class: 'row nw' }, h('div', { class: 'grow', style: { position: 'relative' } }, qIn), h('button', { class: 'btn primary', type: 'button', id: 'cfg-hf-go', onclick: () => search() }, icon('search', 15), t('Pesquisar'))),
      h('div', { class: 'row', style: { marginTop: '8px' } }, h('span', { class: 'dim small' }, t('Sugestão:')), h('button', { class: 'chip', type: 'button', id: 'cfg-hf-default', onclick: () => { qIn.value = (M.default || {}).repo || ''; search(); } }, (M.default || {}).repo || '')),
      searchBox);
  }
  async function search() {
    const q = qIn.value.trim();
    if (!q) { qIn.focus(); return; }
    searchBox.replaceChildren(h('div', { class: 'row muted', style: { marginTop: '14px' } }, h('div', { class: 'spinner' }), t('Pesquisando…')));
    try { found = await api('/api/hf/search?q=' + encodeURIComponent(q)); filesFor = found.results.length === 1 ? found.results[0].id : ''; paintResults(); }
    catch (e) { searchBox.replaceChildren(h('div', { class: 'errbox', style: { whiteSpace: 'normal' } }, e.message)); }
  }
  function paintResults() {
    if (!found) return;
    if (!found.results.length) { searchBox.replaceChildren(h('div', { class: 'empty', style: { marginTop: '14px', padding: '30px 16px' } }, h('h3', null, t('Nada encontrado para «{q}».', { q: found.query })), h('p', null, t('Tente outro nome, um autor (unsloth, bartowski…) ou cole «dono/nome».')))); return; }
    searchBox.replaceChildren(h('div', { class: 'sf-results', style: { marginTop: '14px' } }, found.results.map((r) => resultRow(r))));
    if (filesFor) openFiles(filesFor);
  }
  function resultRow(r) {
    const open = filesFor === r.id;
    return h('div', { class: 'sf-res' + (open ? ' open' : ''), dataset: { repo: r.id } },
      h('div', { class: 'row nw' }, h('div', { class: 'grow' }, h('div', { class: 'nm' }, r.id), h('div', { class: 'muted small' }, '⬇ ' + Number(r.downloads || 0).toLocaleString() + ' · ♥ ' + (r.likes || 0) + (r.pipeline_tag ? ' · ' + r.pipeline_tag : ''))),
        h('a', { class: 'btn ghost sm', href: 'https://huggingface.co/' + r.id, target: '_blank', rel: 'noopener noreferrer', title: t('Abrir a página do modelo') }, icon('globe', 14)),
        h('button', { class: 'btn sm' + (open ? '' : ' primary'), type: 'button', dataset: { act: 'files' }, onclick: () => { filesFor = open ? '' : r.id; paintResults(); } }, open ? t('Fechar') : t('Ver arquivos'))),
      open ? h('div', { class: 'sf-files', id: 'cfg-files-' + r.id.replace(/\W/g, '_') }, h('div', { class: 'row muted' }, h('div', { class: 'spinner' }), t('Lendo os arquivos…'))) : null);
  }
  async function openFiles(repo) {
    const slot = document.getElementById('cfg-files-' + repo.replace(/\W/g, '_'));
    if (!slot) return;
    try {
      const r = await api('/api/hf/files?repo=' + encodeURIComponent(repo));
      slot.replaceChildren(h('div', { class: 'muted small', style: { marginBottom: '6px' } }, t('Escolha a quantização: menos bits = arquivo menor e menos memória, com menos qualidade. A recomendada cabe na RAM deste computador ({r} GB).', { r: (state.hardware || {}).ram_gb || '?' })),
        ...r.files.map((f) => fileRow(repo, f)));
    } catch (e) { slot.replaceChildren(h('div', { class: 'errbox', style: { margin: 0, whiteSpace: 'normal' } }, e.message)); }
  }
  function fileRow(repo, f) {
    const key = repo + '|' + f.name, d = dl.get(key);
    const tag = [f.quant, f.quant && f.quality ? t(QUALITY_LABEL[f.quality] || f.quality) : '', f.parts > 1 ? t('{n} partes', { n: f.parts }) : ''].filter(Boolean).join(' · ');
    return h('div', { class: 'sf-file' + (f.recommended ? ' rec' : ''), dataset: { file: f.name } },
      h('div', { class: 'row nw' }, h('div', { class: 'grow' }, h('div', { class: 'nm', title: f.name }, f.name), h('div', { class: 'muted small' }, fmtBytes(f.size) + (tag ? ' · ' + tag : ''))),
        f.recommended ? h('span', { class: 'chip on' }, t('recomendado')) : null,
        !f.fits && f.size ? h('span', { class: 'chip', title: t('Pode não caber na RAM deste computador') }, t('pesado')) : null,
        f.installed ? h('span', { class: 'chip solid' }, t('baixado')) : null,
        d ? h('button', { class: 'btn sm', type: 'button', dataset: { act: 'cancel' }, onclick: () => d.stop() }, icon('stop', 13), t('Cancelar'))
          : h('button', { class: 'btn sm primary', type: 'button', dataset: { act: 'download' }, onclick: () => startDownload(repo, f) }, icon('download', 14), f.installed ? t('Usar') : t('Baixar e usar'))),
      d ? h('div', { class: 'sf-prog' }, h('div', { class: 'bar' }, h('i', { style: { width: (d.total ? Math.round(100 * d.done / d.total) : 0) + '%' } })), h('div', { class: 'muted small' }, progText(d))) : null);
  }
  const progText = (d) => d.total ? `${fmtBytes(d.done)} / ${fmtBytes(d.total)} (${Math.round(100 * d.done / d.total)}%)` + (d.speed ? ' · ' + fmtBytes(d.speed) + '/s' + (d.total > d.done ? ' · ' + fmtEta((d.total - d.done) / d.speed) : '') : '') : t('Começando…');

  async function startDownload(repo, f) {
    if (f.installed) { try { await api('/api/models/use', { method: 'POST', body: { name: f.name.split('/').pop() } }); toast(t('Modelo em uso: {n}', { n: f.name }), 'ok'); reload(); } catch (e) { toast(e.message, 'err'); } return; }
    let jid = '';
    try { jid = (await api('/api/hf/download', { method: 'POST', body: { repo, name: f.name, use: true } })).job_id; }
    catch (e) { if (e.status === 409 && e.data && e.data.job_id) jid = e.data.job_id; else { toast(e.message, 'err'); return; } }
    track(repo, f.name, jid, f.size);
  }
  function track(repo, name, jid, size) {
    const key = repo + '|' + name;
    if (dl.has(key)) return;
    const d = { done: 0, total: size || 0, speed: 0, jid, stop: () => api('/api/jobs/' + jid + '/cancel', { method: 'POST', body: {} }).catch(() => {}) };
    dl.set(key, d);
    refreshRows();
    d.close = events('/api/jobs/' + jid + '/events', (ev) => {
      if (ev.type === 'progress') { d.done = ev.done; d.total = ev.total || d.total; d.speed = ev.speed || 0; refreshRows(true); }
      else if (ev.type === 'error') { toast(ev.message || t('O download falhou.'), 'err'); }
      else if (ev.type === 'cancelled') { toast(t('Download cancelado (continua de onde parou se você baixar de novo).')); }
      else if (ev.type === 'result') { toast(t('Modelo baixado e em uso: {n}', { n: ev.data.name }), 'ok'); }
    }, () => { dl.delete(key); reload(); });
  }
  function refreshRows(light) {
    if (light) {   // só a barra e o texto, sem recriar os botões (um clique no meio não se perde)
      dl.forEach((d, key) => { const [repo, name] = key.split('|'); const row = box.querySelector(`.sf-file[data-file="${CSS.escape(name)}"]`); if (!row) return; const bar = row.querySelector('.bar > i'), tx = row.querySelector('.sf-prog .muted'); if (bar) bar.style.width = (d.total ? Math.round(100 * d.done / d.total) : 0) + '%'; if (tx) tx.textContent = progText(d); });
      const def = document.getElementById('cfg-default-prog'); const dd = [...dl.values()][0]; if (def && dd) { def.querySelector('.bar > i').style.width = (dd.total ? Math.round(100 * dd.done / dd.total) : 0) + '%'; def.querySelector('.muted').textContent = progText(dd); }
      return;
    }
    paint(); if (found) paintResults();
  }
  async function pullDefault() {
    const d = M.default || {};
    try {
      const r = await api('/api/hf/files?repo=' + encodeURIComponent(d.repo));
      const f = r.files.find((x) => x.name === d.file) || r.files.find((x) => x.recommended) || r.files[0];
      if (!f) throw new Error(t('O repositório não tem arquivos GGUF.'));
      await startDownload(d.repo, f);
      const slot = document.getElementById('cfg-default'); if (slot) slot.append(h('div', { class: 'sf-prog', id: 'cfg-default-prog', style: { flexBasis: '100%' } }, h('div', { class: 'bar' }, h('i')), h('div', { class: 'muted small' }, t('Começando…'))));
    } catch (e) { toast(e.message, 'err'); }
  }

  paint();
  // downloads que já estavam rodando (a página foi trocada e voltou): reconecta
  try { (await api('/api/jobs?status=running&kind=download:')).jobs.forEach((j) => { const m = j.meta || {}; if (m.repo && m.name) track(m.repo, m.name, j.id, 0); }); } catch (e) { /* sem a lista: tudo bem */ }
  if (ctx && ctx.pullDefault) { state.ctx = {}; if (!M.local.length) pullDefault(); }
  return box;
}

// ===================================================================================== EDITOR
async function editorTab() {
  const cat = await catalog();
  const sc = JSON.parse(JSON.stringify(state.settings.scriber));
  const typeSel = h('select', { id: 'cfg-type', onchange: (e) => { sc.type = e.target.value; } }, ['fiction', 'professional', 'academic'].map((g) => h('optgroup', { label: t({ fiction: 'Ficção', professional: 'Profissional', academic: 'Acadêmico e científico' }[g]) },
    Object.entries(cat.types).filter(([, v]) => v.group === g).map(([k, v]) => h('option', { value: k, selected: k === sc.type }, t(v.label))))));
  typeSel.value = sc.type;
  return h('div', null,
    cfgCard(t('Novos projetos'),
      h('div', { class: 'grid2' }, field(t('Tipo de escrita padrão'), typeSel), field(t('Idioma padrão'), select(Object.entries(cat.languages).map(([k, v]) => [k, t(v)]), sc.language, (v) => { sc.language = v; }, { id: 'cfg-lang' }))),
      field(t('Conteúdo'), select([['free', t('Livre (SFW e NSFW, para adultos)')], ['sfw', t('Só SFW')]], sc.content, (v) => { sc.content = v; }, { id: 'cfg-content' }), t('Os limites fixos não mudam: nada sexual com menores nem com pessoas reais. Cada projeto pode escolher o seu.'))),
    cfgCard(t('IA no editor'),
      h('div', { class: 'grid2' }, field(t('Expandir: palavras por parágrafo'), numInput(sc, 'expand_words', 10, 3000, 10)), field(t('Expandir: palavras por fala/diálogo'), numInput(sc, 'dialogue_words', 10, 3000, 10))),
      checkbox(t('Pesquisar na web por padrão nas ações da IA'), sc.web, (v) => { sc.web = v; })),
    cfgCard(t('Edição'),
      checkbox(t('Salvar automaticamente enquanto escreve'), sc.autosave, (v) => { sc.autosave = v; }),
      checkbox(t('Corretor ortográfico do navegador'), sc.spellcheck, (v) => { sc.spellcheck = v; }),
      field(t('Pontos de retorno guardados por projeto'), numInput(sc, 'undo_keep', 5, 100, 1), t('Antes de mudanças grandes (importar, restaurar) o texto anterior vai para o histórico.'))),
    saveRow(async () => { await saveSettings({ scriber: sc }); await refreshState(); }));
}

// ===================================================================================== APARÊNCIA
// Tamanho da interface: de 50% a 200%, de 5 em 5. O controle só aplica ao soltar (a interface inteira muda de tamanho, e o próprio controle junto).
function scaleField(current, onSave) {
  const out = h('output', { id: 'ui-scale-out' }, current + '%');
  const inp = h('input', { type: 'range', id: 'ui-scale', min: 50, max: 200, step: 5, value: current, 'aria-label': t('Tamanho da interface'),
    oninput: () => { out.textContent = inp.value + '%'; }, onchange: () => onSave(Number(inp.value)) });
  const presets = h('div', { class: 'row', style: { gap: '6px', flexWrap: 'wrap', marginTop: '8px' } },
    [50, 75, 90, 100, 110, 125, 150, 175, 200].map((v) => h('button', { type: 'button', class: 'btn sm' + (v === current ? ' on' : ''), dataset: { scale: v }, onclick: () => { inp.value = v; out.textContent = v + '%'; onSave(v); } }, v + '%')));
  return field(t('Tamanho da interface'), h('div', null, h('div', { class: 'scalebox' }, inp, out), presets), t('De 50% a 200%. Aumenta ou diminui tudo; útil em telas grandes ou pequenas.'));
}
// Fontes da interface: usam as fontes do próprio computador (nada é baixado). «Outra fonte» aceita o nome de qualquer fonte instalada.
const FONT_OPTIONS = [['system', 'Sistema', 'padrão do seu computador'], ['inter', 'Inter', 'limpa e moderna'], ['humanist', 'Humanista', 'Segoe UI, Calibri…'], ['rounded', 'Arredondada', 'cantos suaves'],
  ['verdana', 'Verdana', 'larga, ótima para ler na tela'], ['readable', 'Alta legibilidade', 'Atkinson, Lexend, OpenDyslexic…'], ['book', 'Livro', 'serifada de leitura'], ['serif', 'Serifada', 'Georgia'], ['mono', 'Monoespaçada', 'estilo terminal']];
const FONT_CSS = { system: 'var(--font)', inter: 'Inter,"Helvetica Neue",Arial,sans-serif', humanist: '"Segoe UI","Gill Sans",Candara,Optima,Calibri,sans-serif', rounded: 'ui-rounded,"SF Pro Rounded",Nunito,"Varela Round","Arial Rounded MT Bold",sans-serif',
  verdana: 'Verdana,Tahoma,Geneva,sans-serif', readable: '"Atkinson Hyperlegible",Lexend,OpenDyslexic,"Comic Sans MS",Verdana,sans-serif', book: 'Charter,"Sitka Text",Cambria,Georgia,serif', serif: 'Georgia,"Palatino Linotype",serif', mono: 'ui-monospace,Menlo,Consolas,monospace' };
function fontField(u, onSave) {
  const grid = h('div', { class: 'fontgrid', id: 'ui-fonts', role: 'radiogroup', 'aria-label': t('Fonte') });
  const custom = h('input', { type: 'text', id: 'ui-font-custom', maxlength: 60, value: u.font_custom || '', placeholder: t('Nome de uma fonte instalada, ex.: Fira Sans'), 'aria-label': t('Outra fonte') });
  const btns = FONT_OPTIONS.map(([id, label, sub]) => h('button', { type: 'button', class: 'fontopt', role: 'radio', dataset: { font: id }, style: { fontFamily: FONT_CSS[id] },
    onclick: () => { paint(id); onSave({ font: id }); } }, h('b', null, t(label)), h('small', null, t(sub))));
  grid.append(...btns);
  const paint = (cur) => btns.forEach((b) => { const on = b.dataset.font === cur; b.classList.toggle('on', on); b.setAttribute('aria-checked', on ? 'true' : 'false'); });
  paint(u.font === 'custom' ? '' : u.font);
  const apply = () => { const name = custom.value.trim(); if (name) { paint(''); onSave({ font: 'custom', font_custom: name }); } else if (u.font === 'custom') { paint('system'); onSave({ font: 'system', font_custom: '' }); } };
  custom.addEventListener('change', apply);
  return field(t('Fonte'), h('div', null, grid, h('div', { class: 'row nw', style: { marginTop: '10px' } }, h('label', { class: 'f', for: 'ui-font-custom', style: { margin: 0, whiteSpace: 'nowrap' } }, t('Outra fonte')), custom)),
    t('Usa as fontes do seu computador. Se a fonte digitada não estiver instalada, a interface usa a fonte do sistema.'));
}

async function appearance() {
  const save = async (patch, quiet) => { await saveSettings({ ui: patch }); if (!quiet) toast(t('Salvo'), 'ok'); };
  const U = () => ui();
  return h('div', null,
    cfgCard(t('Tema'), themeCards(U().theme, (v) => save({ theme: v })),
      h('div', { class: 'field', style: { marginTop: '16px', marginBottom: 0 } }, h('label', { class: 'f' }, t('Cor de destaque')), accentSwatches(U().accent, (v) => save({ accent: v }, true)),
        h('div', { class: 'hint' }, t('Usada em botões, seleções e destaques.')))),
    cfgCard(t('Leitura e conforto'),
      scaleField(U().scale, (v) => save({ scale: v })),
      field(t('Densidade'), seg([['comfortable', t('Confortável')], ['compact', t('Compacta')]], U().density, (v) => save({ density: v })), t('Compacta mostra mais conteúdo na tela.')),
      fontField(U(), (patch) => save(patch)),
      field(t('Animações'), select([['auto', t('Automático (segue o sistema)')], ['reduce', t('Reduzir animações')], ['full', t('Sempre animar')]], U().motion, (v) => save({ motion: v })), t('“Reduzir” desliga transições e animações — bom para quem sente enjoo com movimento ou usa um computador mais fraco.'))),
    cfgCard(t('Idioma'),
      field(t('Idioma da interface'), select([['auto', t('Automático (navegador)')], ['pt-BR', 'Português (Brasil)'], ['en', 'English']], state.settings.language, async (v) => { await saveSettings({ language: v }); location.reload(); }),
        t('Os textos do terminal (scribeflow, instaladores) seguem o idioma do computador; para forçar um, use SCRIBEFLOW_LANG=pt ou SCRIBEFLOW_LANG=en.'))),
    cfgCard(t('Padrões da aparência'),
      h('p', { class: 'muted small', style: { marginTop: 0 } }, t('Volta o tema, as cores e o conforto de leitura ao original. Seus modelos e projetos não mudam.')),
      h('div', { class: 'row' }, h('button', { class: 'btn sm', onclick: () => window.SCRIBEFLOW_WELCOME && window.SCRIBEFLOW_WELCOME() }, t('Rever as boas-vindas')), h('span', { class: 'grow' }),
        h('button', { class: 'btn sm danger', onclick: async () => { if (await confirmDialog(t('Voltar a aparência e as preferências de uso ao padrão? Seus modelos e projetos não mudam.'), true, t('Restaurar'))) { await api('/api/settings/reset', { method: 'POST', body: { section: 'ui' } }); await refreshState(); location.reload(); } } }, t('Restaurar padrões da aparência')))));
}

// ===================================================================================== AVANÇADO
async function advancedTab() {
  const S = state.settings;
  const m = JSON.parse(JSON.stringify(S.model)), hf = { token: '', connections: S.hf.connections }, w = JSON.parse(JSON.stringify(S.web)), st = { models_dir: S.storage.models_dir || '' };
  const tok = h('input', { type: 'password', id: 'cfg-hf-token', autocomplete: 'off', placeholder: S.hf.token_set ? t('•••••• (já configurado; deixe vazio para manter)') : t('hf_… (opcional)'), oninput: (e) => { hf.token = e.target.value; } });
  const imp = h('input', { type: 'file', accept: '.json,application/json', class: 'hidden', id: 'cfg-import-file', onchange: async (e) => {
    const f = e.target.files[0]; e.target.value = ''; if (!f) return;
    try { const r = await api('/api/settings/import', { method: 'POST', body: JSON.parse(await f.text()) }); toast(t('Configurações importadas: {s}', { s: r.imported.join(', ') }), 'ok'); await refreshState(); location.reload(); } catch (err) { toast(err.message, 'err'); } } });
  return h('div', null,
    cfgCard(t('Execução do modelo'),
      h('div', { class: 'grid2' },
        field(t('Camadas na placa de vídeo'), numInput(m, 'gpu_layers', -1, 999, 1), t('-1 = o máximo possível, 0 = só CPU. Só vale se o motor foi instalado com suporte a GPU; sem memória na placa, o ScribeFlow tenta de novo só na CPU.')),
        field(t('Threads da CPU'), numInput(m, 'threads', 0, 256, 1), t('0 = automático.'))),
      field(t('Descarregar o modelo da memória depois de (min)'), numInput(m, 'idle_unload_min', 0, 1440, 1), t('0 = nunca descarregar. Libera a RAM quando você deixa o ScribeFlow parado.')),
      checkbox(t('Deixar modelos que «pensam» (Qwen3…) pensar antes de responder'), m.thinking, (v) => { m.thinking = v; }),
      h('div', { class: 'hint' }, t('Desligado (recomendado): respostas diretas e bem mais rápidas.'))),
    cfgCard(t('Hugging Face'),
      field(t('Token de acesso'), tok, t('Só é preciso para modelos que exigem login ou aceitar uma licença. Fica salvo neste computador e nunca é mostrado na tela.')),
      h('div', { class: 'grid2' }, field(t('Conexões por download'), numInput(hf, 'connections', 1, 8, 1), t('Mais conexões baixam mais rápido em redes boas (1 a 8).')),
        field(t('Pasta dos modelos'), h('input', { type: 'text', id: 'cfg-models-dir', value: st.models_dir, placeholder: t('padrão: ~/.scribeflow/models'), oninput: (e) => { st.models_dir = e.target.value.trim(); } }), t('Um disco externo ou outra unidade. Vazio = a pasta padrão.')))),
    cfgCard(t('Busca na web (no editor)'),
      h('div', { class: 'grid3' }, field(t('Motor'), select([['auto', t('Automático (DuckDuckGo → Wikipédia)')], ['duckduckgo', 'DuckDuckGo'], ['wikipedia', t('Wikipédia')]], w.engine, (v) => { w.engine = v; })),
        field(t('Resultados'), numInput(w, 'results', 1, 10, 1)), field(t('Páginas lidas'), numInput(w, 'read_pages', 0, 5, 1))),
      h('div', { class: 'hint' }, t('É a única parte do ScribeFlow que acessa a internet além do Hugging Face, e só quando você liga «Pesquisar na web» numa ação da IA.'))),
    saveRow(async () => { await saveSettings({ model: m, hf: { token: hf.token, connections: hf.connections }, web: w, storage: { models_dir: st.models_dir } }); await refreshState(); await refreshModel(); }),
    cfgCard(t('Configurações'),
      h('div', { class: 'row' }, h('button', { class: 'btn sm', type: 'button', onclick: async () => { const r = await fetch('/api/settings/export'); const a = h('a', { href: URL.createObjectURL(await r.blob()), download: 'scribeflow-configuracoes.json' }); document.body.appendChild(a); a.click(); a.remove(); } }, icon('download', 13), t('Exportar')),
        h('button', { class: 'btn sm', type: 'button', onclick: () => imp.click() }, icon('upload', 13), t('Importar')), imp, h('span', { class: 'grow' }),
        h('button', { class: 'btn sm danger', type: 'button', onclick: async () => { if (await confirmDialog(t('Voltar o modelo e o editor ao padrão? O token do Hugging Face, os modelos e os projetos não mudam.'), true, t('Restaurar'))) { await api('/api/settings/reset', { method: 'POST', body: { section: 'model' } }); await api('/api/settings/reset', { method: 'POST', body: { section: 'scriber' } }); await refreshState(); location.reload(); } } }, t('Restaurar padrões'))),
      h('p', { class: 'hint small', style: { marginBottom: 0 } }, t('A exportação não leva o token do Hugging Face. Dados em: {h}', { h: state.home }))));
}
