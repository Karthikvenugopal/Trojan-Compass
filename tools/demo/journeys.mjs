// Extra end-to-end journeys in a real browser: every entry path, resume upload, campus Q&A.
// Usage: node journeys.mjs [name...]
import { writeFileSync } from 'node:fs';
import { APP_URL, OUT, clickReply, launch, send, settle, shot } from './shots.mjs';

const RESUME = `
<h1>Sample Student</h1>
<p>M.S. Computer Science student, University of Southern California (expected 2027)</p>
<h2>Skills</h2><p>Python, PyTorch, SQL, basic machine learning, Git</p>
<h2>Experience</h2>
<p>Built a retrieval-augmented chatbot over course notes as a class project.</p>
<p>Software engineering intern: wrote data pipelines in Python and SQL.</p>
<h2>Coursework</h2><p>Completed CSCI 570 Analysis of Algorithms and an introductory machine learning course.</p>`;

async function text(page, selector) {
  return (await page.locator(selector).last().innerText()).replace(/\s+/g, ' ').slice(0, 260);
}

const journeys = {
  async notsure(page) {
    await page.goto(APP_URL);
    await clickReply(page, "I'm not sure where to start.");
    await clickReply(page, 'Building things');
    await clickReply(page, 'Programming (apps or websites)');
    await clickReply(page, 'I have no experience');
    console.log('  reply:', await text(page, '.message-row.assistant .bubble'));
    console.log('  next step:', await text(page, '.next-step-banner'));
    await shot(page, '11-notsure-recommendations');
    await page.evaluate(() => document.querySelector('#roadmap')?.scrollIntoView({ block: 'start' }));
    await shot(page, '12-notsure-roadmap');
    await clickReply(page, 'Explain these simply');
    console.log('  explain:', await text(page, '.message-row.assistant .bubble'));
    await shot(page, '13-explain-simply');
    await clickReply(page, 'Change direction');
    console.log('  change:', await text(page, '.message-row.assistant .bubble'));
  },
  async goal(page) {
    await page.goto(APP_URL);
    await clickReply(page, 'I know what I want to do.');
    await send(page, 'Research on efficient AI inference. I am a PhD student, I know machine learning well and completed CSCI 567.');
    console.log('  reply:', await text(page, '.message-row.assistant .bubble'));
    console.log('  next step:', await text(page, '.next-step-banner'));
    await page.evaluate(() => document.querySelector('.pathway-panel')?.scrollIntoView({ block: 'start' }));
    await shot(page, '14-goal-graph');
    await page.evaluate(() => document.querySelector('#roadmap')?.scrollIntoView({ block: 'start' }));
    await shot(page, '15-goal-roadmap');
  },
  async resume(page) {
    // Make a small sample PDF, then upload it through the real file input.
    const maker = await page.context().newPage();
    await maker.setContent(RESUME);
    writeFileSync(`${OUT}sample-resume.pdf`, await maker.pdf({ format: 'Letter' }));
    await maker.close();
    await page.goto(APP_URL);
    await page.getByRole('button', { name: /Optional: add a resume/ }).click();
    await page.getByLabel('Upload a resume file').setInputFiles(`${OUT}sample-resume.pdf`);
    await page.waitForFunction(() => document.querySelector('.background-form textarea')?.value.length > 50, null, { timeout: 20000 });
    console.log('  parsed pdf:', (await page.getByLabel('Paste your resume or experience').inputValue()).slice(0, 120));
    await shot(page, '16-resume-loaded');
    await page.getByRole('button', { name: 'Use this background' }).click();
    await settle(page);
    console.log('  reply:', await text(page, '.message-row.assistant .bubble'));
    await send(page, 'Agentic RAG and information retrieval');
    console.log('  reply:', await text(page, '.message-row.assistant .bubble'));
    console.log('  next step:', await text(page, '.next-step-banner'));
    await page.getByRole('button', { name: /What I’m using/ }).click();
    await page.evaluate(() => document.querySelector('.information-panel')?.scrollIntoView({ block: 'start' }));
    await shot(page, '17-resume-information');
    await page.evaluate(() => document.querySelector('#roadmap')?.scrollIntoView({ block: 'start' }));
    await shot(page, '18-resume-roadmap');
  },
  async campus(page) {
    await page.goto(APP_URL);
    await send(page, 'Is any library open right now?');
    console.log('  reply:', await text(page, '.message-row.assistant .bubble'));
    await send(page, 'Who teaches CSCI 572 in Spring 2027 and when does it meet?');
    console.log('  reply:', await text(page, '.message-row.assistant .bubble'));
    await shot(page, '10-campus-questions');
  },
  async mobile(page) {
    await page.setViewportSize({ width: 414, height: 860 });
    await page.goto(APP_URL);
    await shot(page, '19-mobile-welcome');
    await clickReply(page, 'I have an interest to explore.');
    await send(page, 'film directing');
    await clickReply(page, 'I have no experience');
    await page.evaluate(() => document.querySelector('.pathway-panel')?.scrollIntoView({ block: 'start' }));
    await shot(page, '20-mobile-graph');
  },
};

const wanted = process.argv.slice(2);
const { browser, page } = await launch();
for (const [name, run] of Object.entries(journeys)) {
  if (wanted.length && !wanted.includes(name)) continue;
  console.log('---', name);
  try { await run(page); } catch (error) { console.log('FAILED', name, String(error).slice(0, 500)); await shot(page, `error-${name}`); }
}
await browser.close();
