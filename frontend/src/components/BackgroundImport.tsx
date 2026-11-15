import { useRef } from 'react';
import { Paperclip } from 'lucide-react';

/** Native attachment picker only. Reading and sending share the chat request lifecycle. */
export function BackgroundImport({ disabled, onFile }: { disabled: boolean; onFile: (file: File) => void }) {
  const input = useRef<HTMLInputElement>(null);
  return <div className="background-import">
    <button type="button" className="import-toggle" disabled={disabled} onClick={() => input.current?.click()}><Paperclip size={16} aria-hidden="true" /> Attach resume or profile PDF</button>
    <input ref={input} type="file" hidden aria-label="Upload background document" accept=".pdf,.docx" disabled={disabled} onChange={event => { const file = event.target.files?.[0]; event.target.value = ''; if (file) onFile(file); }} />
    <p className="information-privacy">PDF/DOCX, up to 4 MB. Or paste a LinkedIn profile link into the chat. Background goes to the configured AI provider; provider retention is separate. Correct details in “What I’m using.”</p>
  </div>;
}
