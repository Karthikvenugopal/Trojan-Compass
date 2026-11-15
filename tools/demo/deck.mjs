// Render docs/submission/deck.html to a 16:9 PDF and one PNG per slide.
import { chromium } from 'playwright-core';
import { mkdirSync } from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';

const dir = fileURLToPath(new URL('../../docs/submission/', import.meta.url));
mkdirSync(`${dir}slides`, { recursive: true });
const browser = await chromium.launch({ channel: 'msedge', headless: true });
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
await page.goto(pathToFileURL(`${dir}deck.html`).href);
await page.waitForLoadState('networkidle');
await page.emulateMedia({ media: 'print' });
await page.pdf({ path: `${dir}TrojanCompass-deck.pdf`, width: '1920px', height: '1080px', printBackground: true });
await page.emulateMedia({ media: 'screen' });
const slides = page.locator('.slide');
const count = await slides.count();
for (let index = 0; index < count; index += 1) {
  await slides.nth(index).screenshot({ path: `${dir}slides/slide-${String(index + 1).padStart(2, '0')}.png` });
}
console.log(`rendered ${count} slides`);
await browser.close();
