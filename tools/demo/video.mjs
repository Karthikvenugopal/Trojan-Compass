// Record a captioned walkthrough of the live prototype (under 3 minutes).
// Usage: PLAYWRIGHT_BROWSERS_PATH=./.browsers node video.mjs   (app must be running)
import { chromium } from 'playwright-core';
import { copyFileSync, mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { APP_URL, OUT, settle } from './shots.mjs';

const SUBMISSION = fileURLToPath(new URL('../../docs/submission/', import.meta.url));
mkdirSync(`${OUT}video`, { recursive: true });
const browser = await chromium.launch({ channel: 'msedge', headless: true });
const context = await browser.newContext({
  viewport: { width: 1280, height: 720 },
  recordVideo: { dir: `${OUT}video`, size: { width: 1280, height: 720 } },
});
const page = await context.newPage();
const started = Date.now();
const pause = ms => page.waitForTimeout(ms);

async function caption(text) {
  await page.evaluate(value => {
    let bar = document.getElementById('demo-caption');
    if (!bar) {
      bar = document.createElement('div');
      bar.id = 'demo-caption';
      bar.style.cssText = 'position:fixed;left:50%;bottom:22px;transform:translateX(-50%);z-index:9999;max-width:1080px;'
        + 'padding:13px 26px;border-radius:14px;background:rgba(12,16,22,.93);color:#fff;font:600 21px Segoe UI,sans-serif;'
        + 'text-align:center;box-shadow:0 10px 40px rgba(0,0,0,.35);border:1px solid #58c4dd';
      document.body.appendChild(bar);
    }
    bar.textContent = value;
    bar.style.display = value ? 'block' : 'none';
  }, text);
}

async function card(title, subtitle, ms) {
  await page.evaluate(([heading, sub]) => {
    const cover = document.createElement('div');
    cover.id = 'demo-card';
    cover.style.cssText = 'position:fixed;inset:0;z-index:10000;display:flex;flex-direction:column;justify-content:center;'
      + 'padding:0 110px;background:radial-gradient(900px 500px at 78% 12%,#141c27 0,#0c1016 62%);color:#f4f1ea';
    cover.innerHTML = '<div style="color:#58c4dd;font:600 20px Segoe UI;letter-spacing:5px">AI@USC HACKATHON</div>'
      + `<div style="font:400 84px Cambria,Georgia,serif;margin-top:14px">${heading}</div>`
      + `<div style="font:400 30px Segoe UI;color:#cfd5dc;margin-top:18px;max-width:980px;line-height:1.45">${sub}</div>`;
    document.body.appendChild(cover);
  }, [title, subtitle]);
  await pause(ms);
  await page.evaluate(() => document.getElementById('demo-card')?.remove());
}

async function say(text) {
  const box = page.getByLabel('Your message');
  await box.click();
  await box.pressSequentially(text, { delay: 28 });
  await pause(500);
  await page.getByRole('button', { name: 'Send message' }).click();
  await settle(page);
}

async function reply(name) {
  await page.getByRole('button', { name, exact: true }).last().click();
  await settle(page);
}

const scrollTo = (selector, block = 'start') => page.evaluate(([target, where]) =>
  document.querySelector(target)?.scrollIntoView({ block: where, behavior: 'smooth' }), [selector, block]);

await page.goto(APP_URL);
await page.waitForSelector('.welcome');
await card('Trojan <i style="color:#ffd866">Compass</i>', 'Find your path at USC: your interests, mapped to skills, courses, professors, research and events.', 4500);

await caption('Three ways in. Every question is optional, and “I’m not sure” is always OK.');
await pause(4500);
await caption('A student has an interest but no plan yet.');
await reply('I have an interest to explore.');
await pause(1500);
await say('AI in healthcare');
await caption('One question about background, so the path fits the student.');
await say("I'm a master's student in computer science. I know Python and took an intro machine learning course.");

await caption('Real USC courses for next term, each with a reason, seats and official sources.');
await pause(3500);
await page.evaluate(() => document.querySelector('.conversation')?.scrollBy({ top: 330, behavior: 'smooth' }));
await pause(4500);

await caption('The path through the USC knowledge graph: interest → skills → courses → professors.');
await scrollTo('.pathway-panel');
await pause(4000);
await page.locator('.graph-node.kind-skill').first().hover();
await pause(2500);
await caption('Select any node to trace its path. Dashed links are inferred; solid links come from official data.');
await page.locator('.graph-node.kind-course').first().click();
await pause(4500);
await caption('The same graph as an accessible list.');
await page.getByRole('button', { name: 'List' }).click();
await pause(3500);
await page.getByRole('button', { name: 'Graph' }).click();

await caption('A roadmap to keep: what I know → what to learn → courses and research, with one clear next step.');
await scrollTo('#roadmap');
await pause(7000);

await caption('Follow-ups: explain it simply, explore further, or change direction.');
await scrollTo('.chat-panel');
await pause(1200);
await reply('Explain these simply');
await pause(5500);

await caption('It also answers everyday campus questions from live and official sources.');
await say('Is any library open right now?');
await pause(6000);

await caption('');
await card('Every Trojan deserves a <i style="color:#ffd866">map</i>.', '7,306 real USC courses · 39,115 graph edges · sources on every answer · no student data stored.<br><br>Periyakaruppan Nagappan · Riddhi Gupta · Karthik · Abhishek Nair', 6000);

const seconds = Math.round((Date.now() - started) / 1000);
const video = page.video();
await context.close();
const path = await video.path();
copyFileSync(path, `${SUBMISSION}TrojanCompass-demo.webm`);
await browser.close();
console.log(`recorded ${seconds}s -> docs/submission/TrojanCompass-demo.webm`);
