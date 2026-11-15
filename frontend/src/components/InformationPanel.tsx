import { useState } from 'react';
import { ChevronDown, SlidersHorizontal, Check, CircleHelp } from 'lucide-react';
import type { AnswerStatus, InformationEdit, InformationField, InformationSnapshot } from '../types';

const initialFields: InformationField[] = [
  { field: 'direction', label: 'Interests or direction', category: 'fixed', required: true, status: 'not_answered', value: null },
  { field: 'background', label: 'Skills and experience', category: 'fixed', required: true, status: 'not_answered', value: null },
];

interface Props {
  information: InformationSnapshot | null;
  disabled: boolean;
  onSave: (edit: InformationEdit, label: string) => void;
}

/** Student-controlled view. Values and drafts live only in this mounted page. */
export function InformationPanel({ information, disabled, onSave }: Props) {
  const [expanded, setExpanded] = useState(false);
  const fields = information?.fields.length ? information.fields : initialFields;
  const answered = fields.filter(field => field.status !== 'not_answered').length;
  return (
    <section className="information-panel" aria-label="Information for this chat">
      <button type="button" className="information-toggle" aria-expanded={expanded}
        aria-controls="information-content" onClick={() => setExpanded(!expanded)}>
        <span className="information-title"><SlidersHorizontal size={17} aria-hidden="true" /> What I’m using</span>
        <span className="information-count">{answered} of {fields.length} answered</span>
        <ChevronDown size={16} className={expanded ? 'chevron expanded' : 'chevron'} aria-hidden="true" />
      </button>
      <div id="information-content" className="information-content" hidden={!expanded}>
        <p className="information-intro">Before searching: choose an area to explore and share your background. Extra questions depend on your request. “I don’t know” and “None” count as answers.</p>
        <div className={`readiness-note ${information?.ready ? 'ready' : ''}`}>
          {information?.ready ? <Check size={15} aria-hidden="true" /> : <CircleHelp size={15} aria-hidden="true" />}
          <span>{information?.ready ? 'Minimum answers collected. Results depend on the available sourced data.' : 'Before searching, answer the items marked needed. Unknown or None are valid answers.'}</span>
        </div>
        <div className="information-fields">
          {fields.map(field => <AnswerEditor key={`${field.field}:${field.status}:${field.value ?? ''}`}
            field={field} disabled={disabled} onSave={onSave} />)}
        </div>
        {disabled && <p className="information-privacy">Finish sending or clear your current message before editing.</p>}
        <p className="information-privacy">Only in this chat’s memory. Saving sends your correction as a message and updates the reply. Start over, End chat or refresh clears this information. External AI-provider retention is separate.</p>
      </div>
    </section>
  );
}

function AnswerEditor({ field, disabled, onSave }: {
  field: InformationField; disabled: boolean; onSave: Props['onSave'];
}) {
  const [status, setStatus] = useState<AnswerStatus>(field.status);
  const [value, setValue] = useState(field.value ?? '');
  const inputId = `answer-${encodeURIComponent(field.field)}`;
  const changed = status !== field.status || (status === 'provided' && value.trim() !== field.value);
  const valid = status !== 'provided' || value.trim().length > 0;
  return <div className="information-field">
    <div className="information-field-heading">
      <label htmlFor={inputId}>{field.label}</label>
      <span className={`information-badge ${field.required ? 'needed' : ''}`}>
        {field.category === 'fixed' ? 'Core checklist' : 'For this request'}{field.required ? ' · needed' : ''}
      </span>
    </div>
    <div className="answer-controls">
      <select id={inputId} value={status} disabled={disabled}
        onChange={event => setStatus(event.target.value as AnswerStatus)}>
        <option value="not_answered">Not answered</option>
        <option value="unknown">I don’t know</option>
        <option value="none">None</option>
        <option value="provided">Write an answer</option>
      </select>
      <button type="button" className="answer-save" disabled={disabled || !changed || !valid}
        aria-label={`Save ${field.label.toLowerCase()}`}
        onClick={() => onSave({ field: field.field, status, value: status === 'provided' ? value.trim() : null }, field.label)}>
        Save
      </button>
    </div>
    {status === 'provided' && <textarea aria-label={`${field.label} answer`} value={value}
      maxLength={1000} rows={2} disabled={disabled} placeholder="Write a sentence in your own words…"
      onChange={event => setValue(event.target.value)} />}
  </div>;
}
