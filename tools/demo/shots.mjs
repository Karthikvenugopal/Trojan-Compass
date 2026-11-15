// Drive the running app in a real browser and save screenshots.
// Usage: node shots.mjs [scenario...]   (needs the app at http://127.0.0.1:5173)
import { chromium } from 'playwright-core';
import { mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

export const APP_URL = process.env.APP_URL ?? 'http://127.0.0.1:5173';
export const OUT = fileURLToPath(new URL('./out/', import.meta.url));
mkdirSync(OUT, { recursive: true });

export async function launch(options = {}) {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2, ...options });
  const page = await context.newPage();
  page.on('pageerror', error => console.log('PAGE ERROR:', error.message));
  page.on('console', message => { if (message.type() === 'error') console.log('CONSOLE ERROR:', message.text()); });
  return { browser, context, page };
}

export async function send(page, text) {
  await page.getByLabel('Your message').fill(text);
  await page.getByRole('button', { name: 'Send message' }).click();
  await settle(page);
}

export async function clickReply(page, name) {
  await page.getByRole('button', { name, exact: true }).last().click();
  await settle(page);
}

export async function settle(page) {
  await page.waitForSelector('.thinking', { state: 'attached', timeout: 5000 }).catch(() => {});
  await page.waitForSelector('.thinking', { state: 'detached', timeout: 60000 });
  await page.waitForTimeout(500);
}

export async function shot(page, name, options = {}) {
  await page.screenshot({ path: `${OUT}${name}.png`, ...options });
  console.log('saved', name);
}

const scenarios = {
  async welcome(page) {
    await page.goto(APP_URL);
    await page.waitForSelector('.welcome');
    await shot(page, '01-welcome');
    await page.getByRole('button', { name: /Optional: add a resume/ }).click();
    await shot(page, '02-welcome-background');
  },
  async interest(page) {
    await page.goto(APP_URL);
    await clickReply(page, 'I have an interest to explore.');
    await shot(page, '03-interest-question');
    await send(page, 'AI in healthcare');
    await send(page, "I'm a master's student in computer science. I know Python and took an intro machine learning course.");
    await shot(page, '04-recommendations');
    await page.locator('.pathway-panel').scrollIntoViewIfNeeded();
    await page.evaluate(() => document.querySelector('.pathway-panel')?.scrollIntoView({ block: 'start' }));
    await shot(page, '05-graph');
    await page.locator('.graph-node.kind-course').first().click();
    await shot(page, '06-graph-selected');
    await page.evaluate(() => document.querySelector('#roadmap')?.scrollIntoView({ block: 'start' }));
    await shot(page, '07-roadmap');
    await shot(page, '08-full-page', { fullPage: true });
    await page.getByRole('button', { name: 'List' }).click();
    await page.evaluate(() => document.querySelector('.pathway-panel')?.scrollIntoView({ block: 'start' }));
    await shot(page, '09-list-view');
  },
  async campus(page) {
    await page.goto(APP_URL);
    await send(page, 'Is any library open right now?');
    await send(page, 'Who teaches CSCI 572 in Spring 2027 and when does it meet?');
    await shot(page, '10-campus-questions');
  },
};

const wanted = process.argv.slice(2);
if (process.argv[1]?.endsWith('shots.mjs')) {
  const { browser, page } = await launch();
  for (const [name, run] of Object.entries(scenarios)) {
    if (wanted.length && !wanted.includes(name)) continue;
    console.log('---', name);
    try { await run(page); } catch (error) { console.log('FAILED', name, String(error).slice(0, 400)); await shot(page, `error-${name}`); }
  }
  await browser.close();
}
