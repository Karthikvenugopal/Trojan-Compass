# Submission pack

Everything Devpost asks for, in one folder.

| Devpost field | Where it is |
| --- | --- |
| Project description | [DEVPOST.md](DEVPOST.md): problem, solution, tech stack, challenges, what's next. Paste it into Devpost. |
| Slide deck (PDF) | [TrojanCompass-deck.pdf](TrojanCompass-deck.pdf), 14 slides. Source: [deck.html](deck.html); images of each slide in `slides/`. |
| Video demo (max 3 min) | [TrojanCompass-demo.webm](TrojanCompass-demo.webm), 83 seconds, captioned, recorded from the live prototype. Upload it to YouTube (unlisted) and paste the link. |
| Screenshots | `screenshots/` |
| GitHub link | https://github.com/Karthikvenugopal/Trojan-Compass (the repository must be public) |
| Working prototype link | Needs hosting on an account you own; see the main README, "Run". The video and screenshots show the live prototype. |

## Rebuild any of it

With the app running (`http://127.0.0.1:5173`):

```sh
cd tools/demo
npm install
node shots.mjs            # screenshots into tools/demo/out/
node journeys.mjs         # every entry path, resume upload, campus questions, mobile
node deck.mjs             # deck.html -> TrojanCompass-deck.pdf + slides/*.png
npx playwright-core install ffmpeg   # once, for video recording
node video.mjs            # captioned walkthrough -> TrojanCompass-demo.webm
```

The scripts use the Microsoft Edge already installed on Windows (`channel: 'msedge'`).
