import { useState } from 'react';
import { Compass, ExternalLink, UserRound } from 'lucide-react';
import { CareerGuide } from './CareerGuide';
import type { DisplayMessage, InformationEdit } from '../types';
import { RecommendationCard } from './RecommendationCard';

interface ChatMessageViewProps {
  message: DisplayMessage;
  onSuggestedReply: (reply: string) => void;
  isBusy: boolean;
  isLatest?: boolean;
  onInformationEdit?: (edit: InformationEdit, label: string) => void;
}

export function ChatMessageView({ message, onSuggestedReply, isBusy, isLatest = true, onInformationEdit }: ChatMessageViewProps) {
  const [showAll, setShowAll] = useState(false);
  const [selectedCourses, setSelectedCourses] = useState<string[]>([]);
  const isAssistant = message.role === 'assistant';
  const recommendations = message.recommendations ?? [];
  const visibleRecommendations = showAll ? recommendations : recommendations.slice(0, 3);

  return (
    <article className={`message-row ${message.role}`}>
      <div className={`message-avatar ${message.role}`} aria-hidden="true">
        {isAssistant ? <Compass size={17} /> : <UserRound size={16} />}
      </div>
      <div className="message-content">
        <div className="message-label">{isAssistant ? 'Trojan Compass' : 'You'}</div>
        <div className={`bubble ${message.role}`}>{!isAssistant && /^Use my (resume|LinkedIn profile) as background\.\n/.test(message.content) ? (message.content.startsWith('Use my resume') ? 'Resume added as background' : 'LinkedIn profile added as background') : message.content}</div>
        {isAssistant && message.limitations && message.limitations.length > 0 && (
          <ul className="limitations">{message.limitations.map((item, index) => <li key={`${index}-${item}`}>{item}</li>)}</ul>
        )}
        {isAssistant && message.sources && message.sources.length > 0 && (
          <div className="answer-sources" aria-label="Sources">
            <span className="answer-sources-label"><ExternalLink size={13} aria-hidden="true" /> Sources</span>
            {message.sources.map((source) => (
              <a key={source.url} href={source.url} target="_blank" rel="noopener noreferrer">{source.title}</a>
            ))}
          </div>
        )}
        {isAssistant && message.guidance && onInformationEdit && (isLatest
          ? <CareerGuide guidance={message.guidance} disabled={isBusy} onEdit={onInformationEdit} />
          : <details className="earlier-plan"><summary>Earlier plan: {message.guidance.goal ?? 'Exploring directions'}</summary><CareerGuide guidance={message.guidance} disabled onEdit={onInformationEdit} /></details>)}
        {visibleRecommendations.length > 0 && !message.guidance && (
          <div className="recommendation-list" aria-label="Recommendations">
            {visibleRecommendations.map((recommendation) => <RecommendationCard key={recommendation.id} recommendation={recommendation} />)}
          </div>
        )}
        {!!recommendations.length && message.guidance && <details className="other-campus-options"><summary>Other campus options from your search</summary><div className="recommendation-list">{recommendations.map(rec => <RecommendationCard key={rec.id} recommendation={rec} />)}</div></details>}
        {recommendations.length > 3 && !showAll && !message.guidance && (
          <button type="button" className="text-button" onClick={() => setShowAll(true)}>Show {recommendations.length - 3} more recommendations</button>
        )}
        {isAssistant && !!message.course_history_options?.length && (
          <fieldset className="course-history-choices" disabled={isBusy}>
            <legend>Recognize any? Select only courses you completed.</legend>
            <p>These sourced examples are memory aids. You can type other courses below.</p>
            {message.course_history_options.map(course => <div key={course.code}>
              <label><input type="checkbox" checked={selectedCourses.includes(course.code)}
                onChange={event => setSelectedCourses(current => event.target.checked
                  ? [...current, course.code] : current.filter(code => code !== course.code))} /> {course.title}</label>
              {' '}<a href={course.sources[0].url} target="_blank" rel="noopener noreferrer">USC source</a>
            </div>)}
            <button type="button" disabled={isBusy || !selectedCourses.length}
              onClick={() => onSuggestedReply(`I have completed these courses: ${selectedCourses.join(', ')}.`)}>
              Confirm completed courses
            </button>
          </fieldset>
        )}
        {isAssistant && message.suggested_replies && message.suggested_replies.length > 0 && (
          <div className="suggested-replies" aria-label="Suggested replies">
            {message.suggested_replies.map((reply) => <button type="button" key={reply} disabled={isBusy || !isLatest} onClick={() => onSuggestedReply(reply)}>{reply}</button>)}
          </div>
        )}
      </div>
    </article>
  );
}
