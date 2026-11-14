import { useState } from 'react';
import { ArrowUpRight, CalendarDays, BookOpen, ChevronDown, CircleHelp, ExternalLink } from 'lucide-react';
import type { Recommendation } from '../types';

interface RecommendationCardProps {
  recommendation: Recommendation;
}

export function RecommendationCard({ recommendation }: RecommendationCardProps) {
  const [showEvidence, setShowEvidence] = useState(false);
  const Icon = recommendation.kind === 'course' ? BookOpen : CalendarDays;
  const date = recommendation.event?.start ? formatDate(recommendation.event.start, recommendation.event.timezone) : null;
  const end = recommendation.event?.end ? formatDate(recommendation.event.end, recommendation.event.timezone) : null;

  return (
    <article className="recommendation-card">
      <div className="recommendation-heading">
        <span className={`kind-icon ${recommendation.kind}`} aria-hidden="true"><Icon size={17} /></span>
        <span className="kind-label">{recommendation.kind === 'course' ? 'Course' : 'Campus event'}</span>
      </div>
      <h3>{recommendation.title}</h3>
      <p className="recommendation-summary">{recommendation.summary}</p>

      {date && (
        <p className="event-time"><CalendarDays size={15} aria-hidden="true" />
          <span>{date}{end ? ` – ${end}` : ''}{recommendation.event?.timezone ? ` (${recommendation.event.timezone})` : ''}</span>
        </p>
      )}
      {recommendation.course?.term && <p className="detail-line"><b>Term:</b> {recommendation.course.term}</p>}
      {recommendation.kind === 'course' && (recommendation.course?.modality || recommendation.modality) && <p className="detail-line"><b>Format:</b> {recommendation.course?.modality || recommendation.modality}</p>}
      {recommendation.kind === 'event' && recommendation.modality && <p className="detail-line"><b>Format:</b> {recommendation.modality}</p>}
      {recommendation.kind === 'event' && recommendation.status && <p className="detail-line"><b>Status:</b> {recommendation.status}</p>}

      {recommendation.why_relevant.length > 0 && (
        <section className="card-section">
          <h4>Why this helps</h4>
          <ul>{recommendation.why_relevant.map((item, index) => <li key={`${index}-${item}`}>{item}</li>)}</ul>
        </section>
      )}
      {recommendation.benefits.length > 0 && (
        <section className="card-section">
          <h4>{recommendation.kind === 'event' ? 'What you could get from it' : 'What you could learn'}</h4>
          <ul>{recommendation.benefits.map((item, index) => <li key={`${index}-${item}`}>{item}</li>)}</ul>
        </section>
      )}
      {recommendation.prerequisites_or_access.length > 0 && (
        <section className="card-section"><h4>Access and prerequisites</h4>
          <ul>{recommendation.prerequisites_or_access.map((item, index) => <li key={`${index}-${item}`}>{item}</li>)}</ul>
        </section>
      )}
      {recommendation.unknowns.length > 0 && (
        <section className="unknown-note"><CircleHelp size={15} aria-hidden="true" /><div><b>Still to confirm</b><ul>{recommendation.unknowns.map((item, index) => <li key={`${index}-${item}`}>{item}</li>)}</ul></div></section>
      )}

      <div className="next-step">
        <h4>What to do next</h4>
        {recommendation.action_url
          ? <a className="action-link" href={recommendation.action_url} target="_blank" rel="noreferrer">
              {recommendation.kind === 'event' ? 'Open event or registration details' : 'Open course details'} <ArrowUpRight size={15} aria-hidden="true" />
            </a>
          : <p>Check the source links for current details before taking action.</p>}
      </div>

      {recommendation.sources.length > 0 && (
        <section className="sources">
          <h4>Sources</h4>
          <ul>{recommendation.sources.map((source, index) => (
            <li key={`${source.url}-${index}`}>
              <a href={source.url} target="_blank" rel="noreferrer">{source.title} <ExternalLink size={12} aria-hidden="true" /></a>
              {source.checked_at && <span>Checked {formatDate(source.checked_at, null)}</span>}
            </li>
          ))}</ul>
        </section>
      )}

      {recommendation.evidence_path.length > 0 && (
        <div className="evidence">
          <button type="button" aria-expanded={showEvidence} onClick={() => setShowEvidence((value) => !value)}>
            Why this recommendation? <ChevronDown size={15} aria-hidden="true" />
          </button>
          {showEvidence && <p>{recommendation.evidence_path.join(' → ')}</p>}
        </div>
      )}
    </article>
  );
}

function formatDate(value: string, timezone: string | null): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  try {
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: 'medium',
      timeStyle: value.includes('T') ? 'short' : undefined,
      ...(timezone ? { timeZone: timezone } : {}),
    }).format(parsed);
  } catch {
    return value;
  }
}
