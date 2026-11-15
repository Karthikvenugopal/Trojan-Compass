import { useRef, useState } from 'react';
import { Compass, FileText, HelpCircle, Sparkles, Target, Upload } from 'lucide-react';

const paths = [
  { text: "I'm not sure where to start.", title: 'I’m not sure where to start', detail: 'Discover interests through a few easy questions.', Icon: HelpCircle },
  { text: 'I have an interest to explore.', title: 'I have an interest to explore', detail: 'Describe it in your own words and narrow it together.', Icon: Compass },
  { text: 'I know what I want to do.', title: 'I know what I want', detail: 'Name a topic or goal and get a direct path.', Icon: Target },
];
const MAX_BACKGROUND = 3600;
export const BACKGROUND_PREFIX = 'My background (pasted resume or experience):';

interface WelcomeProps {
  onStarter: (text: string) => void;
  disabled: boolean;
}

async function readFile(file: File): Promise<string> {
  if (file.name.toLowerCase().endsWith('.pdf') || file.type === 'application/pdf') {
    // Parsed in the browser; the file itself is never uploaded.
    const pdfjs = await import('pdfjs-dist');
    pdfjs.GlobalWorkerOptions.workerSrc = new URL('pdfjs-dist/build/pdf.worker.min.mjs', import.meta.url).toString();
    const document = await pdfjs.getDocument({ data: await file.arrayBuffer() }).promise;
    const pages: string[] = [];
    for (let number = 1; number <= Math.min(document.numPages, 4); number += 1) {
      const content = await (await document.getPage(number)).getTextContent();
      pages.push(content.items.map(item => ('str' in item ? item.str : '')).join(' '));
    }
    return pages.join('\n');
  }
  return file.text();
}

export function Welcome({ onStarter, disabled }: WelcomeProps) {
  const [open, setOpen] = useState(false);
  const [background, setBackground] = useState('');
  const [note, setNote] = useState('');
  const fileRef = useRef<HTMLInputElement>(null);

  async function handleFile(file: File | undefined) {
    if (!file) return;
    try {
      const text = (await readFile(file)).replace(/\s+\n/g, '\n').replace(/[ \t]+/g, ' ').trim();
      setBackground(text.slice(0, MAX_BACKGROUND));
      setNote(text.length > MAX_BACKGROUND ? `Loaded ${file.name} (trimmed to fit).` : `Loaded ${file.name}. Review it before sending.`);
    } catch {
      setNote('That file could not be read. Paste the text instead.');
    }
  }

  return (
    <section className="welcome" aria-labelledby="welcome-heading">
      <div className="welcome-icon"><Compass size={24} aria-hidden="true" /></div>
      <span className="eyebrow"><Sparkles size={13} aria-hidden="true" /> Courses · Professors · Research · Skills to learn</span>
      <h2 id="welcome-heading">Where would you like to begin?</h2>
      <p>Pick a starting point. Every question is optional, and “I’m not sure” is always OK.</p>
      <div className="starter-list path-list" aria-label="Conversation starters">
        {paths.map(({ text, title, detail, Icon }) => (
          <button key={text} type="button" className="path-card" aria-label={text} disabled={disabled} onClick={() => onStarter(text)}>
            <span className="path-icon" aria-hidden="true"><Icon size={18} /></span>
            <span className="path-title">{title}</span>
            <span className="path-detail">{detail}</span>
          </button>
        ))}
      </div>
      <div className="background-box">
        <button type="button" className="background-toggle" aria-expanded={open} onClick={() => setOpen(!open)}>
          <FileText size={15} aria-hidden="true" /> Optional: add a resume, LinkedIn text or past experience
        </button>
        {open && (
          <div className="background-form">
            <textarea aria-label="Paste your resume or experience" value={background} maxLength={MAX_BACKGROUND} rows={5}
              placeholder="Paste resume, LinkedIn “About”, or a few lines about courses and projects you’ve done…"
              onChange={event => { setBackground(event.target.value); setNote(''); }} />
            <div className="background-actions">
              <input ref={fileRef} type="file" accept=".pdf,.txt,.md,text/plain,application/pdf" hidden
                aria-label="Upload a resume file" onChange={event => void handleFile(event.target.files?.[0])} />
              <button type="button" className="background-upload" onClick={() => fileRef.current?.click()}><Upload size={14} aria-hidden="true" /> Upload PDF or text</button>
              <button type="button" className="background-send" disabled={disabled || background.trim().length < 20}
                onClick={() => onStarter(`${BACKGROUND_PREFIX}\n${background.trim()}`)}>Use this background</button>
            </div>
            <p className="background-note">{note || 'Read in your browser and sent only as a chat message. Nothing is stored; remove contact details if you like.'}</p>
          </div>
        )}
      </div>
    </section>
  );
}
