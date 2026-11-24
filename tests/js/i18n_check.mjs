// Lista as frases em português da interface que não têm tradução em en.js:
//  - literais t('...') em qualquer arquivo de web/js;
//  - textos dos mapas usados com t(variável) (labels.js e os rótulos de scriber_ui.js).
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'scribeflow', 'web', 'js');
const EN = (await import(pathToFileURL(join(root, 'en.js')).href)).default;
const files = [];
(function walk(d) { for (const f of readdirSync(d)) { const p = join(d, f); if (statSync(p).isDirectory()) walk(p); else if (f.endsWith('.js') && f !== 'en.js') files.push(p); } })(root);

const missing = new Set();
const lit = /(?<![\w.$])t\(\s*(?:'((?:[^'\\\n]|\\.)*)'|"((?:[^"\\\n]|\\.)*)")/g;
for (const f of files) {
  const src = readFileSync(f, 'utf8');
  for (const m of src.matchAll(lit)) {
    const s = (m[1] ?? m[2]).replace(/\\'/g, "'").replace(/\\"/g, '"').replace(/\\n/g, '\n');
    if (!(s in EN)) missing.add(s);
  }
}
const bag = new Set();
const walkv = (v) => { if (typeof v === 'string') bag.add(v); else if (Array.isArray(v)) v.forEach(walkv); else if (v && typeof v === 'object') Object.values(v).forEach(walkv); };
const lb = await import(pathToFileURL(join(root, 'labels.js')).href);
walkv(lb.SORTS.map(([, l]) => l)); walkv(lb.SETTINGS_TABS.map(([, l]) => l)); walkv(lb.QUALITY_LABEL);
// mapas de scriber_ui.js (rótulos usados com t(variável)): lidos do texto, porque o módulo depende do navegador
const ui = readFileSync(join(root, 'scriber_ui.js'), 'utf8');
for (const name of ['PRESET_LABEL', 'GROUP_LABEL', 'ALIGN_LABEL']) {
  const m = ui.match(new RegExp('export const ' + name + ' = \\{([^}]*)\\}'));
  if (m) for (const x of m[1].matchAll(/:\s*'((?:[^'\\]|\\.)*)'/g)) bag.add(x[1]);
}
for (const s of bag) if (!(s in EN)) missing.add(s);
const empty = Object.entries(EN).filter(([, v]) => !String(v).trim()).map(([k]) => k);
console.log(JSON.stringify({ missing: [...missing], empty, keys: Object.keys(EN).length }));
