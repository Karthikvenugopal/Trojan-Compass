import { useEffect, useRef, useState } from 'react';
import { FileText, Upload, X } from 'lucide-react';
import { importDocument, importLinkedIn } from '../lib/api';

/** Imports are immediately used as a student turn; all content stays in active memory. */
export function BackgroundImport({ disabled, onUse }: { disabled: boolean; onUse: (text: string) => void }) {
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState<'resume' | 'LinkedIn profile'>('resume');
  const [text, setText] = useState('');
  const [url, setUrl] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const pending = useRef<AbortController | null>(null);
  useEffect(() => () => pending.current?.abort(), []);
  function close() { pending.current?.abort(); pending.current = null; setBusy(false); setText(''); setUrl(''); setError(''); setOpen(false); }
  function useBackground(value: string) {
    const trimmed = value.trim();
    if (!trimmed || Array.from(trimmed).length > 20000) { setError('Background must be between 1 and 20,000 characters. Nothing was truncated.'); return; }
    const message = `Use my ${kind} as background.\n${trimmed}`;
    close(); onUse(message);
  }
  async function load(read: (signal: AbortSignal) => Promise<{ text: string }>) {
    pending.current?.abort();
    const controller = new AbortController(); pending.current = controller;
    setBusy(true); setError('');
    try {
      const result = await read(controller.signal);
      if (!controller.signal.aborted && pending.current === controller) useBackground(result.text);
    } catch (caught) {
      if (!controller.signal.aborted) setError(caught instanceof Error ? caught.message : 'Could not read this background. Upload a PDF or paste relevant text instead.');
    } finally { if (pending.current === controller) { pending.current = null; setBusy(false); } }
  }
  function readFile(file: File) {
    const format = file.name.toLowerCase().split('.').pop();
    if ((format !== 'pdf' && format !== 'docx') || file.size > 4 * 1024 * 1024) { setError('Choose a PDF or DOCX under 4 MB.'); return; }
    void load(signal => importDocument(file, format, signal));
  }
  return <section className="background-import" aria-label="Import background">
    {!open ? <button type="button" className="import-toggle" disabled={disabled} onClick={() => setOpen(true)}><FileText size={16} aria-hidden="true" /> Add a resume or LinkedIn background <span>Optional</span></button> : <div className="import-review">
      <header><h3>Add your background</h3><button type="button" aria-label="Close and clear import" onClick={close}><X size={16} aria-hidden="true" /></button></header>
      <div className="import-kinds"><button type="button" disabled={busy} aria-pressed={kind === 'resume'} onClick={() => { setKind('resume'); setError(''); }}>Resume</button><button type="button" disabled={busy} aria-pressed={kind === 'LinkedIn profile'} onClick={() => { setKind('LinkedIn profile'); setError(''); }}>LinkedIn</button></div>
      <p>{kind === 'resume' ? 'Choose your resume and Compass will use it directly as background.' : 'Use your public profile link. If LinkedIn blocks access, upload its PDF export or paste relevant text.'}</p>
      <p className="information-privacy">Adding background sends its text in your conversation to the configured AI provider; provider retention is separate. Compass keeps it only in active memory. Correct extracted details in “What I’m using.” Start over, End chat or refresh clears it.</p>
      {kind === 'LinkedIn profile' && <div><label>LinkedIn profile URL<input type="url" value={url} disabled={busy || disabled} onChange={event => setUrl(event.target.value)} placeholder="https://www.linkedin.com/in/your-profile" /></label><button type="button" disabled={busy || disabled || !url.trim()} onClick={() => void load(signal => importLinkedIn(url.trim(), signal))}>Use LinkedIn profile</button></div>}
      <label className="upload-control"><Upload size={15} aria-hidden="true" /> {kind === 'resume' ? 'Add resume PDF or DOCX' : 'Add profile PDF or DOCX'}<input type="file" aria-label="Upload background document" accept=".pdf,.docx" disabled={disabled || busy} onChange={event => { const file = event.target.files?.[0]; event.target.value = ''; if (file) readFile(file); }} /></label>
      {busy && <p role="status">Reading your background…</p>}{error && <p role="alert">{error}</p>}
      <details><summary>Paste background instead</summary><label>Background text<textarea rows={5} value={text} disabled={busy || disabled} onChange={event => setText(event.target.value)} placeholder="Paste relevant experience, skills or coursework." /></label>
      <p>Up to 20,000 characters, within the conversation’s total limit. Nothing is truncated.</p><button type="button" disabled={disabled || busy || !text.trim() || Array.from(text.trim()).length > 20000 || /^https?:\/\/\S+$/i.test(text.trim())} onClick={() => useBackground(text)}>Use background</button></details>
    </div>}
  </section>;
}
