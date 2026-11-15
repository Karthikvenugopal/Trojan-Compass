import { useState } from 'react';
import { ArrowRight, CheckCircle2, CircleHelp, Compass, FlaskConical, Users, BookOpen } from 'lucide-react';
import type { CareerGuidance, GuidanceAction, InformationEdit } from '../types';

interface Props {
  guidance: CareerGuidance;
  disabled: boolean;
  onEdit: (edit: InformationEdit, label: string) => void;
}
const statuses = { known: 'Self-reported strength', learning: 'Currently learning', not_yet_learned: 'Confirmed development need', unknown: 'Not assessed' };

/** A plan in the current conversation, never a saved student dashboard. */
export function CareerGuide({ guidance, disabled, onEdit }: Props) {
  const [tab, setTab] = useState<'course' | 'faculty' | 'research' | 'event'>(guidance.actions[0]?.kind ?? 'course');
  const question = guidance.next_question;
  const skill = question?.requested_fields[0]?.startsWith('skills.')
    ? guidance.skills.find(s => `skills.${s.name.toLowerCase()}` === question.requested_fields[0]) : null;
  const groups = [
    { kind: 'course' as const, label: 'Learning', icon: BookOpen },
    { kind: 'faculty' as const, label: 'Faculty & instructors', icon: Users },
    { kind: 'research' as const, label: 'Research pathways', icon: FlaskConical },
    { kind: 'event' as const, label: 'Campus connections', icon: Compass },
  ];
  return <section className="career-guide" aria-label="Career guide">
    <header className="career-guide-header">
      <span className="eyebrow">{guidance.mode === 'plan' ? 'Your working roadmap' : 'Explore your direction'}</span>
      <h3>{guidance.goal ?? 'A direction you can grow into'}</h3>
      <p>{guidance.headline}</p>
    </header>
    {!!guidance.suggested_paths.length && <div className="career-options">
      {guidance.suggested_paths.map(path => <article key={path.id}>
        <h4>{path.title}</h4><p>{path.why_consider}</p>
        <a href={path.sources[0].url} target="_blank" rel="noopener noreferrer">Explore the occupation</a>
        <button type="button" disabled={disabled} onClick={() => onEdit({ field: 'target', status: 'provided', value: path.title }, 'career target')}>Explore this path <ArrowRight size={14} aria-hidden="true" /></button>
      </article>)}
    </div>}
    {!!guidance.skills.length && <div className="career-skill-section">
      <h4>Your skill check</h4>
      <p>Only skills you explicitly haven’t learned are marked as development needs. Unknown is a question, not a gap.</p>
      <div className="career-skills">{guidance.skills.map(item => <div className={`career-skill ${item.status}`} key={item.name}>
        <span>{item.status === 'known' ? <CheckCircle2 size={17} aria-hidden="true" /> : <CircleHelp size={17} aria-hidden="true" />}<b>{item.name}</b></span>
        <span className="skill-state">{statuses[item.status]}</span>
        <details><summary>Why this matters</summary><p>{item.basis}</p><a href={item.sources[0].url} target="_blank" rel="noopener noreferrer">Occupation evidence</a>
          {!!item.student_evidence.length && <p>You said: “{item.student_evidence[0].quote}”</p>}
          <label>Update assessment <select aria-label={`Update ${item.name} assessment`} disabled={disabled} value="" onChange={event => {
            const status = event.target.value;
            const value = status === 'known' ? `I am comfortable with ${item.name}.` : status === 'learning' ? `I am learning ${item.name}.` : `I have not learned ${item.name} yet.`;
            if (status) onEdit({ field: `skills.${item.name.toLowerCase()}`, status: status === 'unknown' ? 'unknown' : 'provided', value: status === 'unknown' ? null : value }, item.name);
          }}><option value="" disabled>Choose an update…</option><option value="known">Comfortable</option><option value="learning">Learning</option><option value="not_yet_learned">Not learned yet</option><option value="unknown">Not sure</option></select></label>
        </details>
      </div>)}</div>
      {skill && question && <fieldset className="career-skill-check" disabled={disabled}>
        <legend>One useful check: {skill.name}</legend>
        <div className="suggested-replies">
          {[
            ['I’m comfortable', `I am comfortable with ${skill.name}.`],
            ['I’m learning', `I am learning ${skill.name}.`],
            ['Not learned yet', `I have not learned ${skill.name} yet.`],
          ].map(([label, value]) => <button type="button" key={label} onClick={() => onEdit({ field: `skills.${skill.name.toLowerCase()}`, status: 'provided', value }, skill.name)}>{label}</button>)}
          <button type="button" onClick={() => onEdit({ field: `skills.${skill.name.toLowerCase()}`, status: 'unknown', value: null }, skill.name)}>I’m not sure</button>
        </div>
      </fieldset>}
    </div>}
    {!!guidance.steps.length && <div className="career-roadmap"><h4>Your next steps</h4><ol>
      {guidance.steps.map((step, index) => <li key={step.id}><span className="step-number" aria-hidden="true">{index + 1}</span><div><b>{step.title}</b><p>{step.description}</p>
        {!!step.action_ids.length && <span className="step-evidence">{step.action_ids.length} connected options below</span>}</div></li>)}
    </ol></div>}
    {!!guidance.actions.length && <div className="career-actions">
      <div className="career-action-tabs" aria-label="Explore plan actions">{groups.map(({ kind, label, icon: Icon }) => <button type="button" key={kind} aria-pressed={tab === kind} onClick={() => setTab(kind)}><Icon size={15} aria-hidden="true" />{label}<span>{guidance.actions.filter(a => a.kind === kind).length}</span></button>)}</div>
      <div className="career-action-list">{guidance.actions.filter(action => action.kind === tab).map(action => <Action key={action.id} action={action} />)}
        {!guidance.actions.some(a => a.kind === tab) && <p>No verified {groups.find(g => g.kind === tab)?.label.toLowerCase()} match in the connected data yet. This does not mean USC has none.</p>}
      </div>
    </div>}
    <details className="career-limitations"><summary>Evidence and limits of this plan</summary><ul>{guidance.limitations.map(text => <li key={text}>{text}</li>)}</ul></details>
  </section>;
}
function Action({ action }: { action: GuidanceAction }) {
  return <article className="career-action">
    <span className="action-type">{action.kind === 'faculty' ? 'Listed course instructor' : action.kind === 'research' ? 'Research pathway' : action.kind}{action.term ? ` · ${action.term}` : ''}</span>
    <h4>{action.title}</h4><p>{action.summary}</p><p className="action-reason">{action.why_relevant}</p>
    <span className="availability-note">{action.availability === 'unknown' ? 'Availability unknown' : 'Snapshot evidence · verify current access'}</span>
    {!!action.checks.length && <details><summary>Before taking this step</summary><ul>{action.checks.map(check => <li key={check}>{check}</li>)}</ul></details>}
    <a href={action.url} target="_blank" rel="noopener noreferrer">{action.kind === 'faculty' ? 'View teaching evidence' : 'View official source'} <ArrowRight size={13} aria-hidden="true" /></a>
  </article>;
}
