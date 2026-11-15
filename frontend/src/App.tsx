import { useRef, useState } from 'react';
import { Compass, RotateCcw, ShieldCheck, SquarePen } from 'lucide-react';
import { ChatMessageView } from './components/ChatMessageView';
import { MessageComposer } from './components/MessageComposer';
import { Welcome } from './components/Welcome';
import { BackgroundImport } from './components/BackgroundImport';
import { InformationPanel } from './components/InformationPanel';
import { chatApi, ChatApiError, isMockMode, importDocument, importLinkedIn } from './lib/api';
import type { ChatApi } from './lib/api';
import type { ChatMessage, DisplayMessage, InformationEdit, InformationSnapshot } from './types';
import { decodeResponse } from './lib/response';
import './styles.css';

interface AppProps {
  api?: ChatApi;
  mockMode?: boolean;
}

const INTRO = 'Welcome to Trojan Compass. Explore possible careers or build a working plan for a goal you have. We’ll check your starting point, then connect skills, learning, faculty and research. Unknown and None are valid answers. Resume or LinkedIn background is optional.';

export default function App({ api = chatApi, mockMode = isMockMode }: AppProps) {
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [draft, setDraft] = useState('');
  const [pendingText, setPendingText] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<ChatApiError | null>(null);
  const [status, setStatus] = useState('');
  const [ended, setEnded] = useState(false);
  const [information, setInformation] = useState<InformationSnapshot | null>(null);
  const [failedEdit, setFailedEdit] = useState<InformationEdit | null>(null);
  const [failedImport, setFailedImport] = useState<{ file?: File; content?: string } | null>(null);
  const busyRef = useRef(false);
  const generationRef = useRef(0);
  const abortRef = useRef<AbortController | null>(null);

  async function sendMessage(rawText: string = draft, edit?: InformationEdit, file?: File, retainedBackground?: string) {
    const visibleText = rawText.trim();
    if (!visibleText || busyRef.current || ended) return;
    busyRef.current = true;
    const requestGeneration = generationRef.current;
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    setPendingText(visibleText);
    setError(null);
    setStatus('Trojan Compass is thinking.');
    let content = retainedBackground ?? visibleText;
    try {
      if (!retainedBackground && file) {
        const format = file.name.toLowerCase().split('.').pop();
        if ((format !== 'pdf' && format !== 'docx') || file.size > 4 * 1024 * 1024) throw new ChatApiError('Choose a PDF or DOCX under 4 MB.', 422);
        const background = await importDocument(file, format, controller.signal);
        content = `Use my resume as background.\n${background.text.trim()}`;
      } else if (!retainedBackground && !edit && /^https:\/\/(?:www\.)?linkedin\.com\/\S+$/i.test(visibleText)) {
        const background = await importLinkedIn(visibleText, controller.signal);
        content = `Use my LinkedIn profile as background.\n${background.text.trim()}`;
      }
      if (requestGeneration !== generationRef.current || controller.signal.aborted) return;
      const history: ChatMessage[] = messages.map(({ role, content: messageContent, edit: priorEdit, asked_field }) => ({ role, content: messageContent, ...(priorEdit ? { edit: priorEdit } : {}), ...(asked_field ? { asked_field } : {}) }));
      const requestMessages: ChatMessage[] = [...history, { role: 'user', content, ...(edit ? { edit } : {}) }];
      const charCount = requestMessages.reduce((total, item) => total + Array.from(item.content).length, 0);
      const bodyBytes = new TextEncoder().encode(JSON.stringify({ messages: requestMessages })).byteLength;
      if (requestMessages.length > 64 || requestMessages.some((item) => Array.from(item.content).length > (item.role === 'user' && /^Use my (resume|LinkedIn profile) as background\.\n/.test(item.content) ? 20400 : 4000)) || charCount > 24000 || bodyBytes > 65536) {
        throw new ChatApiError('This conversation reached the API size limit. Start a fresh chat to continue; nothing was sent or truncated.', 422, 'conversation_too_large');
      }
      // Imports and normal turns commit only after success; a retry retains private
      // background in memory without putting extracted document text in the composer.
      const rawResponse: unknown = await api.send({ messages: requestMessages }, controller.signal);
      if (requestGeneration !== generationRef.current || controller.signal.aborted) return;
      const response = decodeResponse(rawResponse);
      const userMessage: DisplayMessage = { id: createId(), role: 'user', content, ...(edit ? { edit } : {}) };
      const assistantMessage: DisplayMessage = {
        id: createId(), role: 'assistant', content: response.message,
        asked_field: response.asked_field,
        recommendations: response.recommendations,
        limitations: response.limitations,
        suggested_replies: response.suggested_replies,
        course_history_options: response.course_history_options,
        sources: response.sources,
        guidance: response.guidance,
      };
      setMessages((current) => [...current, userMessage, assistantMessage]);
      if (response.information?.fields.length) setInformation(response.information);
      setFailedEdit(null);
      setFailedImport(null);
      setDraft('');
      setError(null);
      setStatus('New response received.');
    } catch (caught) {
      if (requestGeneration !== generationRef.current || controller.signal.aborted) return;
      const apiError = caught instanceof ChatApiError
        ? caught
        : new ChatApiError('Something went wrong. Your message is still here; please retry.', 0);
      setError(apiError);
      setDraft(visibleText);
      setFailedEdit(edit ?? null);
      setFailedImport(/^Use my (resume|LinkedIn profile) as background\.\n/.test(content)
        ? { content } : file ? { file } : null);
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

  function saveInformation(edit: InformationEdit, label: string) {
    const answer = edit.status === 'provided' ? edit.value : edit.status === 'unknown' ? 'I don’t know' : edit.status === 'none' ? 'None' : 'Not answered';
    void sendMessage(`Update my ${label.toLowerCase()}: ${answer}`, edit);
  }

  function endChat() {
    generationRef.current += 1;
    abortRef.current?.abort();
    abortRef.current = null;
    busyRef.current = false;
    setMessages([]);
    setInformation(null);
    setFailedEdit(null);
    setFailedImport(null);
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
    setInformation(null);
    setFailedEdit(null);
    setFailedImport(null);
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
          <p>Connect your career goals to skills, courses, faculty and research.</p>
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
            {messages.map((message, index) => (
              <ChatMessageView key={message.id} message={message} isLatest={index === messages.length - 1} isBusy={loading || draft.trim().length > 0} onSuggestedReply={(reply) => void sendMessage(reply)} onInformationEdit={saveInformation} />
            ))}
            {pendingText && <div className="pending-row"><div className="pending-user"><b>You</b><p>{pendingText}</p></div></div>}
            {loading && <div className="thinking" role="status"><span className="dot-loader" aria-hidden="true"><i /><i /><i /></span><span>Finding a helpful next step…</span></div>}
          </div>

          {error && (
            <div className="error-box" role="alert">
              <div><b>{isOversized ? 'Let’s start fresh' : 'We couldn’t send that yet'}</b><p>{error.message}</p></div>
              {isOversized
                ? <button type="button" className="secondary-button" onClick={startFresh}>Start a fresh chat</button>
                : <button type="button" className="secondary-button" onClick={() => void sendMessage(draft, failedEdit ?? undefined, failedImport?.file, failedImport?.content)} disabled={loading || !draft.trim()}>Retry</button>}
            </div>
          )}

          {ended && <div className="ended-note"><b>Chat ended.</b> Your conversation and draft were cleared from this page. Refreshing also starts a new conversation. This does not control external model-provider retention.</div>}

          {!ended && <BackgroundImport key={`import-${generationRef.current}`} disabled={loading || draft.trim().length > 0} onFile={file => void sendMessage("Resume attached", undefined, file)} />}
          {!ended && <MessageComposer value={draft} onChange={value => { setDraft(value); setFailedEdit(null); setFailedImport(null); }} onSubmit={() => void sendMessage(draft, failedEdit ?? undefined, failedImport?.file, failedImport?.content)} disabled={loading} />}
        </section>

        {!ended && <InformationPanel key={generationRef.current} information={information}
          disabled={loading || draft.trim().length > 0}
          onSave={(edit, label) => {
            const answer = edit.status === 'provided' ? edit.value
              : edit.status === 'unknown' ? 'I don’t know' : edit.status === 'none' ? 'None' : 'Not answered';
            void sendMessage(`Update my ${label.toLowerCase()}: ${answer}`, edit);
          }} />}

        <p className="privacy-note">No login or profile needed. Your conversation stays in this page’s memory and clears when you end the chat or refresh.</p>
        <div className="new-chat-row"><button type="button" className="subtle-button" onClick={startFresh} disabled={!conversationStarted && !draft}><RotateCcw size={14} aria-hidden="true" /> Start over</button></div>
      </main>
      <div className="sr-only" role="status" aria-live="polite" aria-atomic="true">{status}</div>
    </div>
  );
}

function createId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}
