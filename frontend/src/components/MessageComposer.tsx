import { FormEvent, KeyboardEvent } from 'react';
import { ArrowUp, LoaderCircle } from 'lucide-react';

interface MessageComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  disabled: boolean;
}

export function MessageComposer({ value, onChange, onSubmit, disabled }: MessageComposerProps) {
  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSubmit();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      onSubmit();
    }
  }

  return (
    <form className="composer" onSubmit={handleSubmit} aria-label="Send a message">
      <label htmlFor="message-input" className="visually-hidden">Your message</label>
      <textarea id="message-input" aria-label="Your message" value={value} onChange={(event) => onChange(event.target.value)} onKeyDown={handleKeyDown}
        placeholder="Send a message or LinkedIn profile link…" maxLength={4000} rows={1} disabled={disabled} />
      <button type="submit" className="send-button" aria-label="Send message" disabled={disabled || value.trim().length === 0}>
        {disabled ? <LoaderCircle size={18} className="spin" aria-hidden="true" /> : <ArrowUp size={19} aria-hidden="true" />}
      </button>
      <p className="composer-hint">Enter to send · Shift + Enter for a new line</p>
    </form>
  );
}
