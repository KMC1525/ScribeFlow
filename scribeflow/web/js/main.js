import { api } from './api.js';
import { setLang, t } from './i18n.js';
import { applyUi } from './prefs.js';
import { installShell, maybeWelcome } from './shell.js';
import { h, icon } from './ui.js';

// Estado global compartilhado entre as telas
export const state = { settings: null, hardware: {}, model: {}, version: '', home: '', ctx: {} };

// Telas da barra lateral: «Projetos» é a tela inicial (todos os projetos + barra de pesquisa).
export const NAV = [['projects', 'Projetos', 'doc'], ['settings', 'Configurações', 'config']];
const VIEWS = { projects: () => import('./views/projects.js'), project: () => import('./views/project.js'), settings: () => import('./views/settings.js') };
const ALIASES = { config: 'settings', models: 'settings', home: 'projects', main: 'projects', scriber: 'projects' };   // endereços antigos/curtos

// Recarrega a página (uma vez por falha: sem laço se o problema continuar). Devolve true se recarregou.
function reloadPage(force) {
  try {
    const last = Number(sessionStorage.getItem('scribeflow.reload') || 0);
    if (!force && Date.now() - last < 30000) return false;
    sessionStorage.setItem('scribeflow.reload', String(Date.now()));
  } catch (e) { if (!force) return false; }
  location.reload();
  return true;
}

export function go(route, ctx) {
  route = ALIASES[route] || route;
  state.ctx = ctx || {};
  if (location.hash === '#/' + route) render(); else location.hash = '#/' + route;
}
export const openProject = (id, tab) => { state.ctx = {}; location.hash = '#/project/' + id + (tab ? '/' + tab : ''); };

export async function refreshState() {
  const s = await api('/api/state');
  // o servidor foi reiniciado numa versão nova com esta página aberta: os módulos da página (já carregados) não combinam mais com os do servidor
  if (state.version && s.version && s.version !== state.version) { if (reloadPage()) return s; }
  Object.assign(state, { settings: s.settings, hardware: s.hardware, model: s.model, warnings: s.warnings || [], version: s.version, diskVersion: s.disk_version || '', home: s.home });
  setLang(state.settings.language);
  applyUi(state.settings.ui);   // aparência (tema, cor, escala…) vinda do servidor; o cache local já pintou a tela no primeiro quadro
  return s;
}
export async function saveSettings(patch) {
  state.settings = await api('/api/settings', { method: 'PUT', body: patch });
  setLang(state.settings.language);
  applyUi(state.settings.ui);
  renderSide();
  return state.settings;
}
export async function refreshModel() { state.model = (await api('/api/models')); renderSide(); return state.model; }

function route() {
  const m = location.hash.match(/^#\/(\w+)/);
  const r = m ? (ALIASES[m[1]] || m[1]) : 'projects';
  return VIEWS[r] ? r : 'projects';
}

export function renderSide() {
  const side = document.getElementById('side');
  if (!side) return;
  const cur = route() === 'project' ? 'projects' : route();
  const collapsed = localStorage.getItem('scribeflow.side') === '1';
  side.classList.toggle('collapsed', collapsed);
  const m = state.model || {}, ready = !!(m.active && m.engine && m.engine.installed);
  const stale = state.diskVersion && state.diskVersion !== state.version;   // há uma versão mais nova instalada do que a que está rodando
  const label = !m.active ? t('Nenhum modelo baixado') : (m.engine && !m.engine.installed ? t('Motor de IA não instalado') : m.active.replace(/\.gguf$/i, ''));
  side.replaceChildren(
    h('a', { class: 'brand', href: '#/projects', title: 'ScribeFlow', onclick: () => { state.ctx = {}; } }, h('span', { class: 'logo', 'aria-hidden': 'true' }, 'S'), h('span', { class: 'word' }, 'ScribeFlow'), h('span', { class: 'sr-only' }, ' — ' + t('tela inicial'))),
    h('button', { class: 'searchbtn', type: 'button', title: t('Buscar (Ctrl+K)'), onclick: () => shell && shell.openPalette() }, icon('search', 16), h('span', null, t('Buscar…')), h('span', { class: 'kbd' }, 'Ctrl K')),
    h('nav', { 'aria-label': t('Telas') }, NAV.map(([id, lab, ic]) => h('a', { class: 'item' + (cur === id ? ' active' : ''), href: '#/' + id, title: t(lab), 'aria-current': cur === id ? 'page' : null, onclick: () => { state.ctx = {}; } },
      icon(ic, 19), h('span', { class: 'lbl' }, t(lab))))),
    h('div', { class: 'foot' },
      h('div', { class: 'chipstat', id: 'side-model', role: 'button', tabindex: '0', title: t('Modelo de texto (IA)') + ': ' + label, onclick: () => go('settings', { tab: 'model' }), onkeydown: (e) => { if (e.key === 'Enter') go('settings', { tab: 'model' }); } },
        h('span', { class: 'dot ' + (ready ? 'ok' : 'warn') }), h('span', { class: 't' }, label)),
      stale ? h('div', { class: 'small t', style: { padding: '4px', color: 'var(--warn, #f5b942)' } }, t('Versão {v} instalada: feche o ScribeFlow e abra de novo.', { v: state.diskVersion })) : null,
      h('div', { class: 'row', style: { justifyContent: 'space-between', padding: '0 4px' } },
        h('span', { class: 'dim small t' }, 'v' + state.version),
        h('button', { class: 'btn ghost icon sm', title: t('Recolher menu'), 'aria-label': t('Recolher menu'), onclick: () => { localStorage.setItem('scribeflow.side', collapsed ? '0' : '1'); renderSide(); } }, icon('panel', 16)))));
}

let renderToken = 0;
async function render() {
  const token = ++renderToken, r = route(), main = document.getElementById('main');
  document.title = 'ScribeFlow — ' + t((NAV.find(([id]) => id === (r === 'project' ? 'projects' : r)) || [0, 'Projetos'])[1]);
  renderSide();
  main.replaceChildren(h('div', { class: 'page' }, h('div', { class: 'spinner' })));
  let mod;
  try { mod = await VIEWS[r](); }
  catch (e) {
    // Não deu para carregar os arquivos da tela (ex.: o ScribeFlow foi atualizado com esta página aberta e ela ficou com arquivos de outra versão).
    console.error(e);
    if (reloadPage()) return;
    if (token !== renderToken) return;
    main.replaceChildren(h('div', { class: 'page narrow' }, h('div', { class: 'errbox' },
      h('p', { style: { margin: '0 0 8px' } }, t('Não foi possível carregar esta tela. Isso costuma acontecer quando o ScribeFlow é atualizado com a página aberta.')),
      h('p', { class: 'small', style: { margin: '0 0 12px' } }, t('Recarregue a página (Ctrl+F5). Se continuar, feche o ScribeFlow, abra de novo com o comando scribeflow e recarregue.')),
      h('p', { class: 'mono small dim', style: { margin: '0 0 12px' } }, String((e && e.message) || e)),
      h('button', { class: 'btn primary', onclick: () => reloadPage(true) }, t('Recarregar a página')))));
    return;
  }
  try {
    if (token !== renderToken) return;
    const root = h('div');
    main.replaceChildren(root);
    main.scrollTop = 0;
    const m = location.hash.match(/^#\/project\/([\w-]+)(?:\/(\w+))?/);
    await (r === 'project' ? mod.default(root, state.ctx || {}, m ? m[1] : '') : mod.default(root, state.ctx || {}));
  } catch (e) {
    console.error(e);
    main.replaceChildren(h('div', { class: 'page narrow' }, h('div', { class: 'errbox' }, t('Algo deu errado:') + ' ' + (e.message || e))));
  }
}

let shell = null;
addEventListener('scribeflow:go', (e) => { if (e.detail && e.detail.route) go(e.detail.route, e.detail.ctx); });   // telas que não importam o main.js pedem navegação por evento
addEventListener('hashchange', () => { render(); });
(async () => {
  try { await refreshState(); } catch (e) { document.getElementById('main').replaceChildren(h('div', { class: 'page narrow' }, h('div', { class: 'errbox' }, e.message))); return; }
  const skip = document.querySelector('.skip');
  if (skip) { skip.textContent = t('Ir para o conteúdo'); skip.addEventListener('click', (e) => { e.preventDefault(); const m = document.getElementById('main'); if (m) m.focus(); }); }
  const app = { state, NAV, go, saveSettings, renderSide, refreshState, openProject };
  shell = installShell(app);
  render();
  maybeWelcome(app).catch((e) => console.error(e));
})();
window.SCRIBEFLOW_WELCOME = () => maybeWelcome({ state, NAV, go, saveSettings, renderSide, refreshState }, true);
