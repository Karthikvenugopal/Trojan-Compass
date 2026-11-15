import { useEffect, useRef, useState } from 'react';
import { FileText, Upload, X } from 'lucide-react';
import { importDocument } from '../lib/api';

/** Review drafts and uploads stay only in this mounted component's memory. */
export function BackgroundImport({ disabled, onUse }: { disabled: boolean; onUse: (text: string) => void }) {
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState<'resume' | 'LinkedIn profile'>('resume');
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const pending = useRef<AbortController | null>(null);
  useEffect(() => () => pending.current?.abort(), []);
  const prefix = `I reviewed this text from my ${kind}. Use it as background, including relevant skills, experience and coursework:\n`;
  const size = Array.from(prefix + text.trim()).length;
  function close() { pending.current?.abort(); pending.current = null; setBusy(false); setText(''); setError(''); setOpen(false); }
  async function read(file: File) {
    const format = file.name.toLowerCase().split('.').pop();
    if ((format !== 'pdf' && format !== 'docx') || file.size > 4 * 1024 * 1024) { setError('Choose a PDF or DOCX under 4 MB.'); return; }
    pending.current?.abort();
    const controller = new AbortController(); pending.current = controller;
    setBusy(true); setError(''); setText('');
    try {
      const result = await importDocument(file, format, controller.signal);
      if (!controller.signal.aborted && pending.current === controller) setText(result.text);
    } catch (caught) {
      if (!controller.signal.aborted) setError(caught instanceof Error ? caught.message : 'Could not read the document. Paste relevant text instead.');
    } finally { if (pending.current === controller) { pending.current = null; setBusy(false); } }
  }
  return <section className="background-import" aria-label="Import background">
    {!open ? <button type="button" className="import-toggle" disabled={disabled} onClick={() => setOpen(true)}><FileText size={16} aria-hidden="true" /> Add a resume or LinkedIn background <span>Optional</span></button> : <div className="import-review">
      <header><h3>Add your background</h3><button type="button" aria-label="Close and clear import" onClick={close}><X size={16} aria-hidden="true" /></button></header>
      <div className="import-kinds"><button type="button" disabled={busy} aria-pressed={kind === 'resume'} onClick={() => setKind('resume')}>Resume</button><button type="button" disabled={busy} aria-pressed={kind === 'LinkedIn profile'} onClick={() => setKind('LinkedIn profile')}>LinkedIn</button></div>
      <p>{kind === 'resume' ? 'Upload a text PDF or DOCX, or paste relevant experience.' : 'Paste profile text or upload your LinkedIn PDF export. A profile URL alone is not enough.'}</p>
      <label className="upload-control"><Upload size={15} aria-hidden="true" /> Choose PDF or DOCX<input type="file" accept=".pdf,.docx" disabled={disabled || busy} onChange={event => { const file = event.target.files?.[0]; event.target.value = ''; if (file) void read(file); }} /></label>
      {busy && <p role="status">Reading document in memory…</p>}{error && <p role="alert">{error}</p>}
      <label className="import-text-label">Review the text before using it<textarea rows={7} value={text} disabled={busy || disabled} onChange={event => setText(event.target.value)} placeholder="Paste relevant background. Remove contact details or anything you do not want to share." /></label>
      <p className={size > 4000 ? 'import-over-limit' : 'import-counter'}>{size} / 4,000 characters including the introduction.{size > 4000 ? ' Keep relevant sections; nothing will be truncated automatically.' : ''}</p>
      <p className="information-privacy">Uploads are processed in memory and discarded. Nothing is added until you confirm. Using this text sends it in the conversation to the configured AI provider; provider retention is separate. Close, Start over, End chat or refresh clears this draft.</p>
      <button type="button" className="import-use" disabled={disabled || busy || !text.trim() || size > 4000} onClick={() => { const value = prefix + text.trim(); close(); onUse(value); }}>Use this reviewed background</button>
    </div>}
  </section>;
}
