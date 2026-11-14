import { describe, expect, it, vi } from 'vitest';
import { ChatApiError, realChatApi } from './api';
import type { ChatResponse } from '../types';

const response: ChatResponse = { message: 'What interests you?', suggested_replies: ['AI'], recommendations: [], limitations: [] };
const request = { messages: [{ role: 'user' as const, content: 'I am curious about AI.' }] };
const signal = new AbortController().signal;

function fakeResponse(status: number, payload: unknown): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => payload } as Response;
}

describe('stateless chat API adapter', () => {
  it('posts the active conversation to the actual /api/chat route', async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(fakeResponse(200, response));
    vi.stubGlobal('fetch', fetchMock);
    await expect(realChatApi.send(request, signal)).resolves.toEqual(response);
    expect(fetchMock).toHaveBeenCalledWith('/api/chat', expect.objectContaining({
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify(request),
      signal,
    }));
  });

  it('maps the backend error envelope without losing its code or safe message', async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(fakeResponse(503, {
      error: { code: 'chat_unavailable', message: 'Recommendations are temporarily unavailable. Please try again.' },
    }));
    vi.stubGlobal('fetch', fetchMock);
    await expect(realChatApi.send(request, signal)).rejects.toMatchObject({
      name: 'ChatApiError',
      status: 503,
      code: 'chat_unavailable',
      message: 'Recommendations are temporarily unavailable. Please try again.',
    });
  });

  it('identifies both byte-limit and structured invalid-conversation errors', async () => {
    const fetchMock = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(fakeResponse(413, { error: { code: 'conversation_too_large', message: 'Too many bytes.' } }))
      .mockResolvedValueOnce(fakeResponse(422, { error: { code: 'invalid_conversation', message: 'Conversation exceeded limits.' } }));
    vi.stubGlobal('fetch', fetchMock);
    await expect(realChatApi.send(request, signal)).rejects.toBeInstanceOf(ChatApiError);
    await expect(realChatApi.send(request, signal)).rejects.toMatchObject({ status: 422, code: 'invalid_conversation' });
  });
});
