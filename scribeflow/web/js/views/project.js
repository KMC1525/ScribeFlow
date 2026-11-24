// Um projeto aberto: barra (título, tipo, idioma, exportar, menu) + o editor. Rota: #/project/<id>
import { api } from '../api.js';
import { t } from '../i18n.js';
import { go, openProject as navProject, state } from '../main.js';
import { LAST, exportAs, exportJson, historyDialog, importDialog, openDoc, propertiesDialog } from '../scriber_ui.js';
import { confirmDialog, h, icon, modal, popover, toast } from '../ui.js';

let current = null;   // o texto aberto (estado S): o editor se limpa ao sair

export default async function render(root, ctx, pid) {
  if (current) { current.cleanup(); current = null; }
  let S;
  try { S = await openDoc(pid); }
  catch (e) { try { localStorage.removeItem(LAST); } catch (x) { /* ok */ } toast(e.message, 'err'); location.hash = '#/projects'; return; }
  try { localStorage.setItem(LAST, pid); } catch (e) { /* ok */ }
  current = S; S.ctx = ctx || {};
  const body = h('div', { class: 'sc-body', id: 'sc-body' });
  const nameEl = h('button', { class: 'sc-pname', type: 'button', title: t('Renomear o texto'), id: 'sc-pname', onclick: rename }, h('b', null, S.proj.name), icon('edit', 12));
  async function rename() {
    const inp = h('input', { value: S.proj.name, maxlength: 100, id: 'sc-rename' });
    if (await modal(t('Renomear o texto'), inp, [{ label: t('Cancelar'), value: null }, { label: t('Salvar'), value: 'ok', cls: 'primary' }]) !== 'ok' || !inp.value.trim()) return;
    S.proj = await S.api.put('', { name: inp.value.trim() }); nameEl.firstChild.textContent = S.proj.name; document.title = 'ScribeFlow — ' + S.proj.name; S.onRename && S.onRename(S.proj.name);
  }
  const refresh = () => go('project/' + pid);
  const menu = (anchor) => {
    const item = (label, ic, fn, cls) => h('div', { class: 'opt ' + (cls || ''), onclick: () => { pop.close(); fn(); } }, icon(ic, 15), label);
    const pop = popover(anchor, h('div', null,
      item(t('Propriedades (tipo, idioma, formatação)'), 'config', () => propertiesDialog(S, refresh)),
      item(t('Exportar como .docx (Word)'), 'download', () => exportAs(S, 'docx')),
      item(t('Exportar como Markdown (.md)'), 'download', () => exportAs(S, 'md')),
      item(t('Exportar como texto (.txt)'), 'download', () => exportAs(S, 'txt')),
      item(t('Exportar como página (.html)'), 'download', () => exportAs(S, 'html')),
      item(t('Exportar projeto (JSON)'), 'download', () => exportJson(S)),
      item(t('Importar arquivo para o texto (.docx, .md, .txt, .html)'), 'upload', () => importDialog(S, refresh)),
      item(t('Histórico (voltar a uma versão)'), 'undo', () => historyDialog(S, refresh)),
      item(t('Duplicar o texto'), 'copy', async () => { const n = await S.api.post('/duplicate', {}); toast(t('Texto duplicado'), 'ok'); navProject(n.id); }),
      item(t('Todos os projetos'), 'folder', () => { location.hash = '#/projects'; }),
      item(t('Apagar o texto'), 'trash', async () => { if (await confirmDialog(t('Apagar «{n}» e todos os arquivos dele? Isso não pode ser desfeito.', { n: S.proj.name }))) { await api('/api/projects/' + pid, { method: 'DELETE' }); try { localStorage.removeItem(LAST); } catch (e) { /* ok */ } location.hash = '#/projects'; } }, 'danger')));
  };
  const bar = h('header', { class: 'sc-bar' },
    h('a', { class: 'btn ghost icon sm', href: '#/projects', title: t('Todos os projetos'), 'aria-label': t('Todos os projetos') }, icon('arrow', 15)),
    nameEl, h('span', { class: 'chip sc-type', id: 'sc-type' }, t(S.cat.types[S.proj.type].label)), h('span', { class: 'chip dim sc-lang' }, S.proj.language),
    h('span', { class: 'grow' }),
    h('button', { class: 'btn sm', type: 'button', id: 'sc-export', title: t('Baixar o texto como documento do Word'), onclick: () => exportAs(S, 'docx') }, icon('download', 13), t('Baixar .docx')),
    h('button', { class: 'btn ghost icon sm', id: 'sc-menu', title: t('Mais'), type: 'button', onclick: (e) => menu(e.currentTarget) }, icon('more', 16)));
  root.replaceChildren(h('div', { class: 'sc-app', id: 'sc-app' }, bar, body));
  document.title = 'ScribeFlow — ' + S.proj.name;
  try {
    const mod = await import('./scriber_edit.js');
    await mod.default(body, S);
  } catch (e) { console.error(e); body.replaceChildren(h('div', { class: 'page narrow' }, h('div', { class: 'errbox' }, t('Algo deu errado:') + ' ' + (e.message || e)))); }
}
