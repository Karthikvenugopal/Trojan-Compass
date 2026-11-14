import { useRef, useState } from 'react';
import { Compass, RotateCcw, ShieldCheck, SquarePen } from 'lucide-react';
import { ChatMessageView } from './components/ChatMessageView';
import { MessageComposer } from './components/MessageComposer';
import { Welcome } from './components/Welcome';
import { chatApi, ChatApiError, isMockMode } from './lib/api';
import type { ChatApi } from './lib/api';
import type { ChatMessage, ChatResponse, DisplayMessage } from './types';
import './styles.css';

interface AppProps {
  api?: ChatApi;
  mockMode?: boolean;
}

const INTRO = 'Welcome to Trojan Compass. Tell me what you’re interested in, what you’ve tried, or where you hope to go. We can figure out a useful next step together.';

export default function App({ api = chatApi, mockMode = isMockMode }: AppProps) {
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [draft, setDraft] = useState('');
  const [pendingText, setPendingText] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<ChatApiError | null>(null);
  const [status, setStatus] = useState('');
  const [ended, setEnded] = useState(false);
  const busyRef = useRef(false);
  const generationRef = useRef(0);
  const abortRef = useRef<AbortController | null>(null);

  async function sendMessage(rawText: string = draft) {
    const content = rawText.trim();
    if (!content || busyRef.current || ended) return;

    const history: ChatMessage[] = messages.map(({ role, content: messageContent }) => ({ role, content: messageContent }));
    const requestMessages: ChatMessage[] = [...history, { role: 'user', content }];
    const charCount = requestMessages.reduce((total, item) => total + Array.from(item.content).length, 0);
    const bodyBytes = new TextEncoder().encode(JSON.stringify({ messages: requestMessages })).byteLength;
    if (requestMessages.length > 64 || requestMessages.some((item) => Array.from(item.content).length > 4000) || charCount > 24000 || bodyBytes > 65536) {
      setError(new ChatApiError('This conversation reached the API size limit. Start a fresh chat to continue; nothing was sent or truncated.', 422, 'conversation_too_large'));
      setDraft(content);
      setStatus('Conversation is too long. Start a fresh chat to continue.');
      return;
    }

    // Keep the turn out of committed history until it succeeds. A retry sends this one draft once.
    busyRef.current = true;
    const requestGeneration = generationRef.current;
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    setPendingText(content);
    setError(null);
    setStatus('Trojan Compass is thinking.');

    try {
      const rawResponse: unknown = await api.send({ messages: requestMessages }, controller.signal);
      if (requestGeneration !== generationRef.current || controller.signal.aborted) return;
      const response = decodeResponse(rawResponse);
      const userMessage: DisplayMessage = { id: createId(), role: 'user', content };
      const assistantMessage: DisplayMessage = {
        id: createId(), role: 'assistant', content: response.message,
        recommendations: response.recommendations,
        limitations: response.limitations,
        suggested_replies: response.suggested_replies,
      };
      setMessages((current) => [...current, userMessage, assistantMessage]);
      setDraft('');
      setError(null);
      setStatus('New response received.');
    } catch (caught) {
      if (requestGeneration !== generationRef.current || controller.signal.aborted) return;
      const apiError = caught instanceof ChatApiError
        ? caught
        : new ChatApiError('Something went wrong. Your message is still here; please retry.', 0);
      setError(apiError);
      setDraft(content);
      setStatus('Message was not sent. Your text is available to retry.');
    } finally {
      if (requestGeneration === generationRef.current) {
        busyRef.current = false;
        abortRef.current = null;
        setLoading(false);
        setPendingText(null);
      }
    }
  }

  function endChat() {
    generationRef.current += 1;
    abortRef.current?.abort();
    abortRef.current = null;
    busyRef.current = false;
    setMessages([]);
    setDraft('');
    setPendingText(null);
    setLoading(false);
    setError(null);
    setEnded(true);
    setStatus('Chat ended. Your in-page conversation was cleared. Refreshing also starts a new conversation. This does not control external model-provider retention.');
  }

  function startFresh() {
    generationRef.current += 1;
    abortRef.current?.abort();
    abortRef.current = null;
    busyRef.current = false;
    setMessages([]);
    setDraft('');
    setPendingText(null);
    setLoading(false);
    setError(null);
    setEnded(false);
    setStatus('Fresh chat started.');
  }

  function handleStarter(text: string) {
    setEnded(false);
    void sendMessage(text);
  }

  const isOversized = error?.status === 413 || error?.code === 'conversation_too_large' || error?.code === 'invalid_conversation';
  const conversationStarted = messages.length > 0 || pendingText !== null || ended || draft.length > 0 || error !== null;

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand" aria-label="Trojan Compass">
          <span className="brand-mark" aria-hidden="true"><Compass size={22} /></span>
          <span>Trojan <b>Compass</b></span>
        </div>
        <div className="topbar-actions">
          {mockMode && <span className="demo-pill">Demo mode · synthetic data</span>}
          {conversationStarted && !ended && <button className="end-chat" type="button" onClick={endChat}><SquarePen size={15} aria-hidden="true" /> End chat</button>}
        </div>
      </header>

      <main id="home" className="main-content">
        <section className="page-heading" aria-label="About Trojan Compass">
          <span className="section-kicker">A USC student guide</span>
          <h1>Find your next step.</h1>
          <p>Find USC courses and events that help you take your next step.</p>
        </section>

        {mockMode && <div className="demo-disclosure"><ShieldCheck size={15} aria-hidden="true" /><span><b>Demo data:</b> examples are synthetic and do not represent live USC offerings.</span></div>}

        <section className="chat-panel" aria-label="Trojan Compass conversation">
          <div className="conversation" role="log" aria-label="Conversation" aria-live="polite" aria-relevant="additions">
            {!conversationStarted && (
              <div className="welcome-wrap">
                <div className="welcome-message"><span className="assistant-mini" aria-hidden="true"><Compass size={16} /></span><p>{INTRO}</p></div>
                <Welcome onStarter={handleStarter} disabled={loading} />
              </div>
            )}
            {messages.map((message) => (
              <ChatMessageView key={message.id} message={message} isBusy={loading || draft.trim().length > 0} onSuggestedReply={(reply) => void sendMessage(reply)} />
            ))}
            {pendingText && <div className="pending-row"><div className="pending-user"><b>You</b><p>{pendingText}</p></div></div>}
            {loading && <div className="thinking" role="status"><span className="dot-loader" aria-hidden="true"><i /><i /><i /></span><span>Finding a helpful next step…</span></div>}
            {!loading && !error && conversationStarted && messages.length > 0 && messages.at(-1)?.role === 'assistant' && messages.at(-1)?.recommendations?.length === 0 && (
              <p className="empty-recommendations">No recommendations to show yet. Answer the question above or try a different direction.</p>
            )}
          </div>

          {error && (
            <div className="error-box" role="alert">
              <div><b>{isOversized ? 'Let’s start fresh' : 'We couldn’t send that yet'}</b><p>{error.message}</p></div>
              {isOversized
                ? <button type="button" className="secondary-button" onClick={startFresh}>Start a fresh chat</button>
                : <button type="button" className="secondary-button" onClick={() => void sendMessage(draft)} disabled={loading || !draft.trim()}>Retry</button>}
            </div>
          )}

          {ended && <div className="ended-note"><b>Chat ended.</b> Your conversation and draft were cleared from this page. Refreshing also starts a new conversation. This does not control external model-provider retention.</div>}

          {!ended && <MessageComposer value={draft} onChange={setDraft} onSubmit={() => void sendMessage()} disabled={loading} />}
        </section>

        <p className="privacy-note">No login or profile needed. Your conversation stays in this page’s memory and clears when you end the chat or refresh.</p>
        <div className="new-chat-row"><button type="button" className="subtle-button" onClick={startFresh} disabled={!conversationStarted && !draft}><RotateCcw size={14} aria-hidden="true" /> Start over</button></div>
      </main>
      <div className="sr-only" role="status" aria-live="polite" aria-atomic="true">{status}</div>
    </div>
  );
}

function decodeResponse(value: unknown): ChatResponse {
  if (!isRecord(value) || typeof value.message !== 'string') {
    throw new ChatApiError('The server returned an unreadable response. Your message is still here; please retry.', 502);
  }
  if (!Array.isArray(value.suggested_replies) || !Array.isArray(value.recommendations) || !Array.isArray(value.limitations)) {
    throw new ChatApiError('The server response is missing expected fields. Your message is still here; please retry.', 502);
  }
  return value as unknown as ChatResponse;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function createId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}
