import type { ChatRequest, ChatResponse } from '../types';
import { mockChat } from './mock';

export interface ChatApi {
  send(request: ChatRequest, signal: AbortSignal): Promise<ChatResponse>;
}

export class ChatApiError extends Error {
  readonly status: number;
  readonly code: string | null;

  constructor(message: string, status: number, code: string | null = null) {
    super(message);
    this.name = 'ChatApiError';
    this.status = status;
    this.code = code;
  }
}

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '';

export const realChatApi: ChatApi = {
  async send(request, signal) {
    let response: Response;
    try {
      response = await fetch(`${API_BASE_URL}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify(request),
        signal,
      });
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') throw error;
      throw new ChatApiError('We could not reach Trojan Compass. Check your connection and retry.', 0);
    }

    if (!response.ok) {
      const body: unknown = await response.json().catch(() => null);
      const errorBody = isRecord(body) ? body : {};
      const nestedError = isRecord(errorBody.error) ? errorBody.error : {};
      const detailBody = isRecord(errorBody.detail) ? errorBody.detail : {};
      const detail = typeof nestedError.message === 'string'
        ? nestedError.message
        : typeof errorBody.detail === 'string'
          ? errorBody.detail
          : typeof detailBody.message === 'string'
            ? detailBody.message
            : typeof errorBody.message === 'string' ? errorBody.message : null;
      const code = typeof nestedError.code === 'string'
        ? nestedError.code
        : typeof errorBody.code === 'string'
          ? errorBody.code
          : typeof detailBody.code === 'string' ? detailBody.code : null;
      if (response.status === 413 || code === 'conversation_too_large') {
        throw new ChatApiError('This conversation has reached its size limit. Start a fresh chat to continue.', response.status, code);
      }
      throw new ChatApiError(detail ?? 'That did not work. Your message is still here; please retry.', response.status, code);
    }

    return (await response.json()) as ChatResponse;
  },
};

export const mockChatApi: ChatApi = { send: mockChat };

/** Mock data is the default until the backend is connected; it is always labeled in the UI. */
export const chatApi: ChatApi = import.meta.env.VITE_USE_MOCK_API === 'false' ? realChatApi : mockChatApi;
export const isMockMode = chatApi === mockChatApi;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}
