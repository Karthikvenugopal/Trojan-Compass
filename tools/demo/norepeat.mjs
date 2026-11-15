// Browser check: vague answers must never make the app ask the same question twice.
// Usage: node norepeat.mjs   (app must be running)
import { APP_URL, clickReply, launch, send, shot } from './shots.mjs';

const conversations = [
  { start: 'I have an interest to explore.', replies: ['something with data maybe', 'a bit of excel at my old job'] },
  { start: "I'm not sure where to start.", replies: ['I like helping people', 'teaching kids', 'not much really'] },
  { start: 'I know what I want to do.', replies: ['robotics', 'nothing'] },
  { start: null, replies: ['machine learning', 'just some python tutorials', 'Is Leavey Library open now?'] },
];

const { browser, page } = await launch();
let failures = 0;
for (const [number, conversation] of conversations.entries()) {
  await page.goto(APP_URL);
  await page.waitForSelector('.welcome');
  if (conversation.start) await clickReply(page, conversation.start);
  for (const reply of conversation.replies) await send(page, reply);
  const bubbles = await page.locator('.message-row.assistant .bubble').allInnerTexts();
  const questions = bubbles.map(text => text.split('\n')[0].trim());
  const repeated = questions.filter((text, index) => questions.indexOf(text) !== index);
  const cards = await page.locator('.recommendation-card h3').allInnerTexts();
  const roadmap = await page.locator('.next-step-banner h3').count();
  const ok = repeated.length === 0 && cards.length > 0 && roadmap > 0;
  if (!ok) failures += 1;
  console.log(`${ok ? 'PASS' : 'FAIL'} conversation ${number + 1}: ${questions.length} replies, repeated=${repeated.length}, cards=${cards.length}, next step=${roadmap > 0}`);
  for (const question of questions) console.log(`     - ${question.slice(0, 95)}`);
  if (number === 0) await shot(page, '21-vague-answers');
}
await browser.close();
console.log(failures ? `${failures} conversation(s) failed` : 'all conversations passed');
process.exit(failures ? 1 : 0);
