import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App';
import { ChatApiError } from './lib/api';
import type { ChatResponse, Recommendation } from './types';
import type { ChatApi } from './lib/api';

const course: Recommendation = {
  id: 'course-test', kind: 'course', title: 'Intro example course', summary: 'A synthetic course result.',
  why_relevant: ['Connects your interest to core concepts.'], benefits: ['Practice a foundational skill.'],
  prerequisites_or_access: ['Check access with the department.'], unknowns: ['Current offering not verified.'],
  action_url: 'https://example.org/course', sources: [{ url: 'https://example.org/source', title: 'Example source', checked_at: null }],
  evidence_path: ['Interest', 'Skill', 'Course'], event: null, course: { term: null, modality: null }, modality: null, status: null,
};
const event: Recommendation = {
  id: 'event-test', kind: 'event', title: 'AI community event', summary: 'A synthetic event result.',
  why_relevant: ['Meet students who share the topic.'], benefits: ['Learn and connect.'], prerequisites_or_access: [],
  unknowns: [], action_url: 'https://example.org/event', sources: [{ url: 'https://example.org/event-source', title: 'Event source', checked_at: null }], evidence_path: ['Interest', 'Event'],
  event: { start: '2027-02-01T16:00:00-08:00', end: null, timezone: 'America/Los_Angeles' }, course: null,
  modality: 'In person', status: 'Scheduled',
};
function result(message = 'Here are a couple of ideas.', recommendations: Recommendation[] = [course, event]): ChatResponse {
  return { message, suggested_replies: ['I am new to this', 'Change direction'], recommendations, limitations: [] };
}
function apiWith(send: ChatApi['send']): ChatApi { return { send }; }

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

describe('Trojan Compass conversation', () => {
  it('allows a beginner to start with a suggested reply using keyboard interaction', async () => {
    const user = userEvent.setup();
    const send = vi.fn<ChatApi['send']>().mockResolvedValue(result('What part of that topic interests you?'));
    render(<App api={apiWith(send)} mockMode={false} />);
    const starter = screen.getByRole('button', { name: "I'm not sure where to start." });
    await user.tab();
    expect(starter).toHaveFocus();
    await user.keyboard('{Enter}');
    expect(await screen.findByText('What part of that topic interests you?')).toBeInTheDocument();
    expect(send).toHaveBeenCalledWith({ messages: [{ role: 'user', content: "I'm not sure where to start." }] }, expect.any(AbortSignal));
  });

  it('sends free text by Enter and renders readable recommendation cards with sources', async () => {
    const user = userEvent.setup();
    const send = vi.fn<ChatApi['send']>().mockResolvedValue(result());
    render(<App api={apiWith(send)} mockMode={false} />);
    const input = screen.getByRole('textbox', { name: 'Your message' });
    await user.type(input, 'I like AI and healthcare{Enter}');
    expect(await screen.findByRole('heading', { name: 'Intro example course' })).toBeInTheDocument();
    expect(screen.getAllByText('Why this helps').length).toBeGreaterThan(0);
    expect(screen.getByRole('link', { name: /Example source/ })).toHaveAttribute('href', 'https://example.org/source');
    expect(screen.getByText(/Feb 1, 2027/)).toBeInTheDocument();
    expect(screen.getByText('Status:').parentElement).toHaveTextContent('Scheduled');
    expect(screen.getByText('Format:').parentElement).toHaveTextContent('In person');
    expect(send.mock.calls[0]?.[0].messages).toEqual([{ role: 'user', content: 'I like AI and healthcare' }]);
  });

  it('sends clickable suggested replies as the next turn with prior context', async () => {
    const user = userEvent.setup();
    const send = vi.fn<ChatApi['send']>()
      .mockResolvedValueOnce(result('What have you tried?'))
      .mockResolvedValueOnce(result('Thanks. Here are updated ideas.'));
    render(<App api={apiWith(send)} mockMode={false} />);
    await user.click(screen.getByRole('button', { name: 'I have an interest to explore.' }));
    await user.click(await screen.findByRole('button', { name: 'I am new to this' }));
    expect(await screen.findByText('Thanks. Here are updated ideas.')).toBeInTheDocument();
    expect(send).toHaveBeenCalledTimes(2);
    expect(send.mock.calls[1]?.[0].messages).toEqual([
      { role: 'user', content: 'I have an interest to explore.' },
      { role: 'assistant', content: 'What have you tried?' },
      { role: 'user', content: 'I am new to this' },
    ]);
  });

  it('preserves a failed draft and retries without duplicating the latest user message', async () => {
    const user = userEvent.setup();
    const send = vi.fn<ChatApi['send']>()
      .mockRejectedValueOnce(new ChatApiError('Temporary issue. Retry.', 503))
      .mockResolvedValueOnce(result());
    render(<App api={apiWith(send)} mockMode={false} />);
    const input = screen.getByRole('textbox', { name: 'Your message' });
    await user.type(input, 'I want to learn design');
    await user.click(screen.getByRole('button', { name: 'Send message' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Temporary issue. Retry.');
    expect(input).toHaveValue('I want to learn design');
    await user.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByRole('heading', { name: 'Intro example course' })).toBeInTheDocument();
    expect(send).toHaveBeenCalledTimes(2);
    expect(send.mock.calls[0]?.[0].messages).toEqual([{ role: 'user', content: 'I want to learn design' }]);
    expect(send.mock.calls[1]?.[0].messages).toEqual([{ role: 'user', content: 'I want to learn design' }]);
  });

  it('clears the conversation and ignores a response that arrives after End chat', async () => {
    const user = userEvent.setup();
    const pending = deferred<ChatResponse>();
    const send = vi.fn<ChatApi['send']>().mockReturnValue(pending.promise);
    render(<App api={apiWith(send)} mockMode={false} />);
    await user.click(screen.getByRole('button', { name: 'I know what I want to do.' }));
    const signal = send.mock.calls[0]?.[1];
    expect(signal?.aborted).toBe(false);
    await user.click(await screen.findByRole('button', { name: 'End chat' }));
    expect(signal?.aborted).toBe(true);
    pending.resolve(result('Late answer that must not show'));
    expect(await screen.findByText(/Your conversation and draft were cleared/)).toBeInTheDocument();
    expect(screen.queryByText('Late answer that must not show')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Start over' }));
    expect(screen.getByRole('button', { name: "I'm not sure where to start." })).toBeInTheDocument();
  });

  it('offers a fresh start for oversized conversations', async () => {
    const user = userEvent.setup();
    const send = vi.fn<ChatApi['send']>().mockRejectedValue(new ChatApiError('Too many messages.', 413, 'conversation_too_large'));
    render(<App api={apiWith(send)} mockMode={false} />);
    await user.type(screen.getByRole('textbox', { name: 'Your message' }), 'Continue this long conversation');
    await user.click(screen.getByRole('button', { name: 'Send message' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Too many messages.');
    await user.click(screen.getByRole('button', { name: 'Start a fresh chat' }));
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: "I'm not sure where to start." })).toBeInTheDocument();
  });

  it('clears conversation state without writing content to browser storage', async () => {
    const user = userEvent.setup();
    const send = vi.fn<ChatApi['send']>().mockResolvedValue(result());
    const localWrite = vi.spyOn(Storage.prototype, 'setItem');
    render(<App api={apiWith(send)} mockMode={false} />);
    await user.type(screen.getByRole('textbox', { name: 'Your message' }), 'My private interests');
    await user.click(screen.getByRole('button', { name: 'Send message' }));
    await screen.findByRole('heading', { name: 'Intro example course' });
    await user.click(screen.getByRole('button', { name: 'End chat' }));
    expect(screen.queryByText('My private interests')).not.toBeInTheDocument();
    expect(localWrite).not.toHaveBeenCalled();
    localWrite.mockRestore();
  });

  it('expands the evidence path on request', async () => {
    const user = userEvent.setup();
    const send = vi.fn<ChatApi['send']>().mockResolvedValue(result());
    render(<App api={apiWith(send)} mockMode={false} />);
    await user.type(screen.getByRole('textbox', { name: 'Your message' }), 'robotics');
    await user.click(screen.getByRole('button', { name: 'Send message' }));
    const details = (await screen.findAllByRole('button', { name: 'Why this recommendation?' }))[0];
    expect(details).toBeDefined();
    await user.click(details!);
    expect(details).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('Interest → Skill → Course')).toBeInTheDocument();
  });
});

it('recovers from a malformed recommendation instead of crashing the conversation', async () => {
  const user = userEvent.setup();
  const send = vi.fn<ChatApi['send']>()
    .mockResolvedValueOnce({ ...result(), recommendations: [{}] } as ChatResponse)
    .mockResolvedValueOnce(result());
  render(<App api={apiWith(send)} mockMode={false} />);
  const input = screen.getByRole('textbox', { name: 'Your message' });
  await user.type(input, 'Synthetic interest');
  await user.click(screen.getByRole('button', { name: 'Send message' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('unreadable response');
  expect(input).toHaveValue('Synthetic interest');
  await user.click(screen.getByRole('button', { name: 'Retry' }));
  expect(await screen.findByRole('heading', { name: 'Intro example course' })).toBeInTheDocument();
  expect(send.mock.calls[1]?.[0].messages).toEqual([{ role: 'user', content: 'Synthetic interest' }]);
});
