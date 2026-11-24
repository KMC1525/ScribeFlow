// Teste de navegador (Playwright + Chromium): percorre o ScribeFlow como uma pessoa faria.
//   node tests/browser/ui_smoke.mjs <url> [pasta-de-capturas]
import { createRequire } from 'node:module';
import assert from 'node:assert/strict';
import { mkdirSync } from 'node:fs';

const require = createRequire(import.meta.url);
const { chromium } = require('playwright');   // (CommonJS: respeita NODE_PATH, onde o Playwright global fica)
const base = process.argv[2]; const shots = process.argv[3] || '';
if (shots) mkdirSync(shots, { recursive: true });
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 }, deviceScaleFactor: 1, acceptDownloads: true, locale: 'pt-BR' });
const page = await ctx.newPage();
const errors = [];
page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text()); });
const shot = async (n) => { if (shots) await page.screenshot({ path: `${shots}/${n}.png` }); };
const step = (s) => console.log('·', s);

await page.goto(base + '/');
await page.waitForSelector('#pj-new');
step('home abre');
// boas-vindas (primeira vez): fecha
const welcome = page.locator('.modal-bg');
if (await welcome.count()) { await shot('01-boas-vindas'); await welcome.locator('button', { hasText: /Explorar sem IA|Começar/ }).first().click(); }
await shot('02-home-vazia');
assert.match(await page.locator('#side .brand').innerText(), /ScribeFlow/);

// novo projeto com system prompt
await page.click('#pj-new');
await page.fill('#pj-new-name', 'O Dragão da Montanha');
await page.fill('#pj-new-sys', 'Escreva em terceira pessoa, no passado. Frases curtas.');
await page.click('.modal .btn.primary');
await page.waitForSelector('#sc-doc');
step('projeto criado e editor aberto');
assert.equal(await page.locator('#sc-system textarea').inputValue(), 'Escreva em terceira pessoa, no passado. Frases curtas.');
assert.equal(await page.locator('#sc-sys-toggle').count(), 1);
assert.equal(await page.locator('text=Lorebook').count(), 0, 'não deve sobrar lorebook');
assert.equal(await page.locator('text=Geração automática').count(), 0, 'não deve haver geração automática');

// digitar no editor + salvar
await page.click('#sc-doc');
await page.keyboard.type('Era uma vez um dragão.');
await page.keyboard.press('Enter');
await page.keyboard.type('— Quem ousa entrar? — rugiu ele.');
await page.waitForFunction(() => document.getElementById('sc-save').textContent.includes('salvo') && !document.getElementById('sc-save').classList.contains('dirty'), null, { timeout: 8000 });
step('texto salvo');
await shot('03-editor');

// system prompt editável e salvo
await page.fill('#sc-sys', 'Escreva em terceira pessoa. Tom sombrio.');
await page.waitForFunction(() => document.getElementById('sc-sys-state').textContent === 'salvo', null, { timeout: 8000 });
const proj = await page.evaluate(async () => (await fetch(location.origin + '/api/projects')).json());
assert.equal(proj.length, 1);
const full = await page.evaluate(async (id) => (await fetch('/api/projects/' + id)).json(), proj[0].id);
assert.equal(full.system_prompt, 'Escreva em terceira pessoa. Tom sombrio.');
step('system prompt salvo no projeto');

// selecionar o parágrafo → ações da IA aparecem; sem modelo, «Corrigir» funciona por regras
await page.click('#sc-doc p:first-child', { clickCount: 3 });
await page.waitForSelector('#sc-act-fix');
for (const a of ['improve', 'expand', 'shorten', 'fix', 'dialogue', 'rewrite']) assert.equal(await page.locator('#sc-act-' + a).count(), 1, a);
await shot('04-selecao-ia');

// sem modelo: «Corrigir» roda por regras (espaços, pontuação), avisa que é sem IA, e «Aceitar» troca o trecho
await page.click('#sc-doc p:first-child', { clickCount: 3 });
await page.keyboard.type('ola  mundo ,tudo bem');
await page.click('#sc-doc p:first-child', { clickCount: 3 });
await page.click('#sc-act-fix');
await page.waitForSelector('#sc-sugg-card');
assert.match(await page.locator('#sc-sugg-card').innerText(), /Sem modelo de IA|Corrigir/);
await shot('04b-sugestao');
await page.click('#sc-sugg-accept');
await page.waitForFunction(() => !document.querySelector('#sc-doc').innerText.includes('  '));
step('ação da IA sem modelo (regras) aplicada');

// aba Revisão (regras) e Estatísticas; aba Web
await page.click('#sc-rtab-review');
await page.click('#sc-review');
await page.waitForSelector('#sc-review-info:not(:empty)');
await page.click('#sc-stats-go');
await page.waitForFunction(() => document.querySelector('#sc-stats-box') && document.querySelector('#sc-stats-box').innerText.includes('Palavras'));
await page.click('#sc-rtab-web');
await page.waitForSelector('#sc-q');
await page.click('#sc-rtab-ai');
step('revisão, estatísticas e aba web abrem');

// exportar projeto em JSON (download)
const [dl] = await Promise.all([page.waitForEvent('download'), page.evaluate(() => document.getElementById('sc-menu').click()).then(() => page.locator('.pop .opt', { hasText: 'Exportar projeto (JSON)' }).click())]);
assert.match(dl.suggestedFilename(), /\.scribeflow\.json$/);
const path = await dl.path();
const fs = await import('node:fs');
const exported = JSON.parse(fs.readFileSync(path, 'utf8'));
assert.equal(exported.format, 'scribeflow.project');
assert.equal(exported.project.system_prompt, 'Escreva em terceira pessoa. Tom sombrio.');
step('exportou JSON');

// volta para a home, importa o JSON como novo projeto
await page.goto(base + '/#/projects');
await page.waitForSelector('.cv-card');
await page.setInputFiles('#pj-import-file', path);
await page.waitForSelector('#sc-doc');
await page.goto(base + '/#/projects');
await page.waitForFunction(() => document.querySelectorAll('.cv-card').length === 2);
step('importou JSON: 2 projetos');
await shot('05-home-2-projetos');

// pesquisa: acha pelo texto do documento
await page.fill('#pj-search', 'ousa');
await page.waitForFunction(() => document.querySelectorAll('.cv-card').length === 2 && document.querySelector('.cv-card .match'));
await page.fill('#pj-search', 'nada-disso');
await page.waitForSelector('.empty:not(.hidden)');
await page.fill('#pj-search', '');

// Configurações → modelo
await page.goto(base + '/#/settings');
await page.waitForSelector('#cfg-model');
assert.equal(await page.locator('#cfg-nctx').inputValue(), '16384');
assert.match(await page.locator('#cfg-default').innerText(), /darrellbest\/Qwen3\.5-2B-Heretic-GGUF/);
await shot('06-config-modelo');
// janela de contexto ajustável
await page.click('#cfg-nctx-chips [data-n="32768"]');
await page.waitForFunction(() => document.getElementById('cfg-nctx').value === '32768');
const st = await page.evaluate(async () => (await fetch('/api/settings')).json());
assert.equal(st.model.n_ctx, 32768);
await page.click('#cfg-nctx-default');
await page.waitForFunction(() => document.getElementById('cfg-nctx').value === '16384');
step('janela de contexto muda e volta ao padrão');

// pesquisa no Hugging Face (falso) e download direto
await page.fill('#cfg-hf-q', 'fakeorg');
await page.press('#cfg-hf-q', 'Enter');
await page.waitForSelector('.sf-res[data-repo="fakeorg/Tiny-Story-GGUF"]');
assert.equal(await page.locator('.sf-res[data-repo="fakeorg/Pixel-Diffusion-GGUF"]').count(), 0, 'modelo de imagem não aparece');
await shot('07-busca-hf');
if (!(await page.locator('.sf-res.open[data-repo="fakeorg/Tiny-Story-GGUF"]').count())) await page.click('.sf-res[data-repo="fakeorg/Tiny-Story-GGUF"] [data-act="files"]');   // um resultado só já abre sozinho
await page.waitForSelector('.sf-file[data-file="Tiny-Story-Q4_K_M.gguf"]');
assert.equal(await page.locator('.sf-file').count(), 2);
await page.click('.sf-file[data-file="Tiny-Story-Q4_K_M.gguf"] [data-act="download"]');
await page.waitForSelector('#cfg-installed .sf-model[data-model="Tiny-Story-Q4_K_M.gguf"].on', { timeout: 15000 });
step('baixou do HF (falso) e ficou em uso');
await shot('08-modelo-baixado');
// o padrão: pesquisar o repositório padrão pela sugestão e baixar
await page.click('#cfg-hf-default');
await page.waitForSelector('.sf-res[data-repo="darrellbest/Qwen3.5-2B-Heretic-GGUF"]');
await page.waitForSelector('.sf-file[data-file="Qwen3.5-2B-Heretic-Q4_K_M.gguf"]');
assert.equal(await page.locator('.sf-file[data-file*="mmproj"]').count(), 0, 'mmproj não é oferecido');
await page.click('.sf-file[data-file="Qwen3.5-2B-Heretic-Q4_K_M.gguf"] [data-act="download"]');
await page.waitForSelector('#cfg-installed .sf-model[data-model="Qwen3.5-2B-Heretic-Q4_K_M.gguf"].on', { timeout: 15000 });
// trocar de volta para o primeiro modelo
await page.click('#cfg-installed .sf-model[data-model="Tiny-Story-Q4_K_M.gguf"] [data-act="use"]');
await page.waitForSelector('#cfg-installed .sf-model[data-model="Tiny-Story-Q4_K_M.gguf"].on');
step('trocou de modelo');
// apagar
page.once('dialog', () => {});
await page.click('#cfg-installed .sf-model[data-model="Tiny-Story-Q4_K_M.gguf"] [data-act="delete"]');
await page.locator('.modal .btn.danger').click();
await page.waitForFunction(() => !document.querySelector('#cfg-installed [data-model="Tiny-Story-Q4_K_M.gguf"]'));
step('apagou modelo');

// outras abas
for (const tab of ['editor', 'appearance', 'advanced']) { await page.click(`.cfgtabs [data-tab="${tab}"]`); await page.waitForSelector('.card'); await shot('09-config-' + tab); }

// tema claro
await page.click('.cfgtabs [data-tab="appearance"]');
await page.click('.themecard[data-theme="light"]');
await page.waitForFunction(() => document.documentElement.dataset.theme === 'light');
await shot('10-tema-claro');
await page.click('.themecard[data-theme="dark"]');

// inglês
await page.evaluate(async () => { await fetch('/api/settings', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ language: 'en' }) }); });
await page.goto(base + '/#/projects'); await page.reload();
await page.waitForSelector('#pj-new');
assert.match(await page.locator('#pj-new').innerText(), /New project/);
await shot('11-ingles');

const real = errors.filter((e) => !/favicon|manifest|404/i.test(e));
assert.deepEqual(real, [], 'erros no console: ' + real.join(' | '));
await browser.close();
console.log('OK: ui_smoke');
