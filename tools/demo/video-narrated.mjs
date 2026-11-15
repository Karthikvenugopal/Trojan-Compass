// Record the narrated demo: each scene lasts at least as long as its voice-over clip,
// then ffmpeg lays the clips over the recording and writes an MP4.
// Usage: PLAYWRIGHT_BROWSERS_PATH=./.browsers node video-narrated.mjs
//   (app running; run voice.py first to create out/voice/*.mp3 and durations.json)
import { chromium } from 'playwright-core';
import { execFileSync } from 'node:child_process';
import { mkdirSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import ffmpeg from 'ffmpeg-static';
import { APP_URL, OUT, settle } from './shots.mjs';

const SUBMISSION = fileURLToPath(new URL('../../docs/submission/', import.meta.url));
const segments = JSON.parse(readFileSync(new URL('./narration.json', import.meta.url), 'utf8'));
const durations = JSON.parse(readFileSync(`${OUT}voice/durations.json`, 'utf8'));
const captions = Object.fromEntries(segments.map(item => [item.id, item.caption]));
mkdirSync(`${OUT}video`, { recursive: true });

const browser = await chromium.launch({ channel: 'msedge', headless: true });
const context = await browser.newContext({
  viewport: { width: 1280, height: 720 },
  recordVideo: { dir: `${OUT}video`, size: { width: 1280, height: 720 } },
});
const page = await context.newPage();
const started = Date.now();
const marks = [];
const pause = ms => page.waitForTimeout(ms);

const CARD = 'position:fixed;inset:0;z-index:10000;display:flex;flex-direction:column;justify-content:center;'
  + 'padding:0 100px;background:radial-gradient(900px 500px at 78% 12%,#141c27 0,#0c1016 62%);color:#f4f1ea;'
  + 'font-family:Segoe UI,sans-serif';

async function card(html) {
  await page.evaluate(([style, body]) => {
    document.getElementById('demo-card')?.remove();
    const cover = document.createElement('div');
    cover.id = 'demo-card';
    cover.style.cssText = style;
    cover.innerHTML = body;
    document.body.appendChild(cover);
  }, [CARD, html]);
}
const uncard = () => page.evaluate(() => document.getElementById('demo-card')?.remove());

async function caption(text) {
  await page.evaluate(value => {
    let bar = document.getElementById('demo-caption');
    if (!bar) {
      bar = document.createElement('div');
      bar.id = 'demo-caption';
      bar.style.cssText = 'position:fixed;left:50%;bottom:20px;transform:translateX(-50%);z-index:9999;max-width:1080px;'
        + 'padding:11px 24px;border-radius:13px;background:rgba(12,16,22,.93);color:#fff;font:600 20px Segoe UI,sans-serif;'
        + 'text-align:center;box-shadow:0 10px 40px rgba(0,0,0,.35);border:1px solid #58c4dd';
      document.body.appendChild(bar);
    }
    bar.textContent = value;
    bar.style.display = value ? 'block' : 'none';
  }, text);
}

/** Run a scene; it never ends before its narration clip does. */
async function scene(id, action, { showCaption = true } = {}) {
  const start = Date.now() - started;
  marks.push({ id, start });
  await caption(showCaption ? captions[id] : '');
  await action();
  const minimum = durations[id] * 1000 + 600;
  const elapsed = Date.now() - started - start;
  if (elapsed < minimum) await pause(minimum - elapsed);
}

async function say(text) {
  const box = page.getByLabel('Your message');
  await box.click();
  await box.pressSequentially(text, { delay: 22 });
  await pause(350);
  await page.getByRole('button', { name: 'Send message' }).click();
  await settle(page);
  if (await page.locator('.error-box').count()) throw new Error('the app showed an error; re-record');
}
async function reply(name) {
  await page.getByRole('button', { name, exact: true }).last().click();
  await settle(page);
  if (await page.locator('.error-box').count()) throw new Error('the app showed an error; re-record');
}
const scrollTo = selector => page.evaluate(target =>
  document.querySelector(target)?.scrollIntoView({ block: 'start', behavior: 'smooth' }), selector);

const KICKER = '<div style="color:#58c4dd;font-weight:600;font-size:20px;letter-spacing:5px">';
const H = '<div style="font:400 66px Cambria,Georgia,serif;margin-top:12px">';
const LI = '<div style="font-size:28px;color:#cfd5dc;margin-top:16px;line-height:1.4">';
const Y = '<span style="color:#ffd866">';

await page.goto(APP_URL);
await page.waitForSelector('.welcome');

await scene('overview', async () => {
  await card(`${KICKER}AI@USC HACKATHON</div><div style="font:400 96px Cambria,Georgia,serif;margin-top:14px">Trojan <i style="color:#ffd866">Compass</i></div>`
    + `${LI}Any interest, turned into a clear path at USC:</div>`
    + `<div style="font-size:34px;margin-top:20px"><span style="color:#fc6255">interest</span> → ${Y}skills</span> → <span style="color:#58c4dd">courses</span> → <span style="color:#83c167">professors</span> → <b>one next step</b></div>`);
}, { showCaption: false });

await scene('users', async () => {
  await card(`${KICKER}WHO IT IS FOR</div>${H}“What should I take <i style="color:#ffd866">next</i>?”</div>`
    + `${LI}• First-years who aren’t sure yet</div>${LI}• Transfer and graduate students new to campus</div>`
    + `${LI}• Advisors and student leaders who guide them</div>`
    + `<div style="font-size:23px;color:#9aa3ad;margin-top:34px">Today the answer is scattered: Schedule of Classes · faculty pages · Handshake · a dozen office websites</div>`);
}, { showCaption: false });

await scene('welcome', async () => {
  await uncard();
  for (const card of await page.locator('.path-card').all()) { await card.hover(); await pause(1700); }
});

await scene('chat', async () => {
  await reply('I have an interest to explore.');
  await say('AI in healthcare');
  await say("I'm a master's student in computer science. I know Python and took an intro machine learning course.");
});

await scene('results', async () => {
  await pause(2500);
  await page.evaluate(() => document.querySelector('.conversation')?.scrollBy({ top: 300, behavior: 'smooth' }));
  await pause(3500);
});

await scene('graph', async () => {
  await scrollTo('.pathway-panel');
  await pause(3000);
  await page.locator('.graph-node.kind-skill').first().hover();
  await pause(3000);
  await page.locator('.graph-node.kind-course').first().click();
  await pause(3500);
});

await scene('roadmap', async () => {
  await scrollTo('#roadmap');
  await pause(5000);
});

await scene('questions', async () => {
  await scrollTo('.chat-panel');
  await pause(900);
  await reply('Explain these simply');
  await pause(2500);
  await say('Is any library open right now?');
  await pause(3500);
});

await scene('usg', async () => {
  await card(`${KICKER}FOR USG: READY TO BECOME A STUDENT SERVICE</div>${H}Built to be <i style="color:#ffd866">adopted</i>.</div>`
    + `${LI}• Runs on <b>public USC data</b>: no special access needed to start</div>`
    + `${LI}• <b>No login, no student data stored</b>: private by design</div>`
    + `${LI}• Refreshes with <b>one script</b>; 7,306 courses and 39,115 graph links today</div>`
    + `${LI}• Next: host it, add real Handshake and club events, bring it to orientation and advising</div>`);
}, { showCaption: false });

await scene('close', async () => {
  await card(`${KICKER}TROJAN COMPASS</div><div style="font:400 84px Cambria,Georgia,serif;margin-top:14px">Every Trojan deserves a <i style="color:#ffd866">map</i>.</div>`
    + `${LI}Periyakaruppan Nagappan · Riddhi Gupta · Karthik · Abhishek Nair</div>`
    + `<div style="font-size:22px;color:#9aa3ad;margin-top:16px">github.com/Karthikvenugopal/Trojan-Compass</div>`);
  await pause(1500);
}, { showCaption: false });

const total = (Date.now() - started) / 1000;
const video = page.video();
await context.close();
const silent = await video.path();
await browser.close();
console.log(`recorded ${total.toFixed(1)}s; mixing narration`);
if (total > 178) throw new Error('longer than 3 minutes: shorten a scene and re-record');

// Lay each clip at its scene's start time, then mux with the recording.
const inputs = marks.flatMap(mark => ['-i', `${OUT}voice/${mark.id}.mp3`]);
const delays = marks.map((mark, index) => `[${index + 1}:a]adelay=${Math.round(mark.start + 350)}:all=1[a${index}]`).join(';');
const mix = `${delays};${marks.map((_, index) => `[a${index}]`).join('')}amix=inputs=${marks.length}:normalize=0[voice]`;
const output = `${SUBMISSION}TrojanCompass-demo.mp4`;
execFileSync(ffmpeg, ['-y', '-loglevel', 'error', '-i', silent, ...inputs, '-filter_complex', mix,
  '-map', '0:v', '-map', '[voice]', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '21', '-pix_fmt', 'yuv420p',
  '-c:a', 'aac', '-b:a', '160k', '-movflags', '+faststart', '-t', String(Math.ceil(total)), output]);
console.log(`wrote docs/submission/TrojanCompass-demo.mp4 (${total.toFixed(0)}s)`);
console.log(marks.map(mark => `${mark.id}@${(mark.start / 1000).toFixed(1)}s`).join('  '));
