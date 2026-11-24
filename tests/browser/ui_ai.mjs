// Teste de navegador das ações da IA, com um modelo e um motor de mentira (ver tests/helpers.py: FakeLlama).
//   node tests/browser/ui_ai.mjs <url> [pasta-de-capturas]
import { createRequire } from 'node:module';
import assert from 'node:assert/strict';
import { mkdirSync } from 'node:fs';

const require = createRequire(import.meta.url);
const { chromium } = require('playwright');
const base = process.argv[2]; const shots = process.argv[3] || '';
if (shots) mkdirSync(shots, { recursive: true });
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 }, locale: 'pt-BR' });
const page = await ctx.newPage();
const errors = [];
page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text()); });
const shot = async (n) => { if (shots) await page.screenshot({ path: `${shots}/${n}.png` }); };
const step = (s) => console.log('·', s);

await page.goto(base + '/');
await page.waitForSelector('#pj-new');
if (await page.locator('.modal-bg').count()) await page.locator('.modal-bg button', { hasText: /Começar|Explorar/ }).first().click();
// o modelo «baixado» aparece na barra lateral e nas configurações
assert.match(await page.locator('#side-model').innerText(), /Qwen3\.5-2B-Heretic-Q4_K_M/);

await page.click('#pj-new');
await page.fill('#pj-new-name', 'Teste da IA');
await page.fill('#pj-new-sys', 'REGRA-UNICA: nunca use a palavra proibida.');
await page.click('.modal .btn.primary');
await page.waitForSelector('#sc-doc');
assert.match(await page.locator('#sc-ed-ai').innerText(), /IA local pronta|ScribeFlow|Qwen/);
await page.click('#sc-doc');
await page.keyboard.type('Ela entrou na sala e olhou em volta.');
await page.keyboard.press('Enter');
await page.keyboard.type('— Ninguém? — disse ela.');
await page.waitForFunction(() => !document.getElementById('sc-save').classList.contains('dirty'));

// Expandir (+150): o texto sugerido chega, mostra que o system prompt chegou ao modelo e que foi guiado por ele
await page.click('#sc-doc p:first-child', { clickCount: 3 });
await page.click('#sc-act-expand');
await page.waitForSelector('#sc-sugg-card');
const sugg = await page.locator('#sc-sugg-text').innerText();
assert.match(sugg, /guiado pelo system prompt/);
assert.match(await page.locator('#sc-sugg-card').innerText(), /Guiado pelo system prompt geral/);
await shot('20-expandir');
await page.click('#sc-sugg-accept');
await page.waitForFunction(() => document.querySelector('#sc-doc').innerText.includes('frio do assoalho'));
step('Expandir segue o system prompt e substitui o trecho');
// Ctrl+Z desfaz
await page.keyboard.press('Control+z');
await page.waitForFunction(() => !document.querySelector('#sc-doc').innerText.includes('frio do assoalho'));
step('Ctrl+Z desfaz');

// Encurtar, Virar diálogo
await page.click('#sc-doc p:first-child', { clickCount: 3 });
await page.click('#sc-act-shorten');
await page.waitForSelector('#sc-sugg-card');
assert.match(await page.locator('#sc-sugg-text').innerText(), /Ela entrou\./);
await page.click('#sc-sugg-drop');
await page.click('#sc-act-dialogue');
await page.waitForSelector('#sc-sugg-card');
assert.equal(await page.locator('#sc-sugg-text p').count(), 2);
await page.click('#sc-sugg-drop');
step('Encurtar e Virar diálogo funcionam');

// o texto selecionado alimenta a barra flutuante
await page.click('#sc-doc p:first-child', { clickCount: 3 });
await page.waitForSelector('#sc-float');
assert.ok(await page.locator('#sc-float button').count() >= 4);

// Revisão com IA: só entram correções que existem no texto
await page.click('#sc-doc p:first-child', { clickCount: 3 });
await page.keyboard.type('Isto é um ezemplo simples.');
await page.click('#sc-rtab-review');
await page.click('#sc-review-ai');
await page.waitForSelector('#sc-issues .sc-issue');
assert.match(await page.locator('#sc-issues').innerText(), /ezemplo/);
await shot('21-revisao-ia');
step('Revisão com IA');

// configurações: testar o modelo
await page.goto(base + '/#/settings');
await page.waitForSelector('#cfg-active');
assert.match(await page.locator('#cfg-active').innerText(), /Qwen3\.5-2B-Heretic-Q4_K_M\.gguf/);
await page.click('#cfg-test');
await page.waitForSelector('.toast.ok');
await page.waitForFunction(() => document.getElementById('cfg-active').innerText.includes('carregado na memória'));
// mudar a janela recarrega o modelo na próxima ação
await page.click('#cfg-nctx-chips [data-n="8192"]');
await page.waitForFunction(() => document.getElementById('cfg-nctx').value === '8192');
await shot('22-config-modelo-ativo');
step('Testar o modelo nas configurações');

const real = errors.filter((e) => !/favicon|manifest|404/i.test(e));
assert.deepEqual(real, [], 'erros no console: ' + real.join(' | '));
await browser.close();
console.log('OK: ui_ai');
