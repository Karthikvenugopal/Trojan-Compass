import { useState } from 'react';
import { Compass, ExternalLink, UserRound } from 'lucide-react';
import type { DisplayMessage } from '../types';
import { RecommendationCard } from './RecommendationCard';

interface ChatMessageViewProps {
  message: DisplayMessage;
  onSuggestedReply: (reply: string) => void;
  isBusy: boolean;
}

export function ChatMessageView({ message, onSuggestedReply, isBusy }: ChatMessageViewProps) {
  const [showAll, setShowAll] = useState(false);
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
        <div className={`bubble ${message.role}`}>{message.content}</div>
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
        {visibleRecommendations.length > 0 && (
          <div className="recommendation-list" aria-label="Recommendations">
            {visibleRecommendations.map((recommendation) => <RecommendationCard key={recommendation.id} recommendation={recommendation} />)}
          </div>
        )}
        {recommendations.length > 3 && !showAll && (
          <button type="button" className="text-button" onClick={() => setShowAll(true)}>Show {recommendations.length - 3} more recommendations</button>
        )}
        {isAssistant && message.suggested_replies && message.suggested_replies.length > 0 && (
          <div className="suggested-replies" aria-label="Suggested replies">
            {message.suggested_replies.map((reply) => <button type="button" key={reply} disabled={isBusy} onClick={() => onSuggestedReply(reply)}>{reply}</button>)}
          </div>
        )}
      </div>
    </article>
  );
}
