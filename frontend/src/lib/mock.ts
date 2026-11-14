import type { ChatApi } from './api';
import type { ChatResponse, Recommendation } from '../types';

const syntheticCourse: Recommendation = {
  id: 'demo-course-1',
  kind: 'course',
  title: 'Example USC course recommendation (synthetic)',
  summary: 'A placeholder course card showing how a real course result will appear.',
  why_relevant: ['Connects the topic you mentioned to a possible academic next step.'],
  benefits: ['Explore foundational ideas', 'Practice applying a concept'],
  prerequisites_or_access: ['Demo only: prerequisites and enrollment access are not verified.'],
  unknowns: ['This is synthetic fixture data, not a real course listing.'],
  action_url: 'https://example.org/usc-course-demo',
  sources: [{ url: 'https://example.org/usc-course-demo', title: 'Synthetic demo source', checked_at: null }],
  evidence_path: ['Your stated interest', 'Related topic', 'Example course'],
  event: null,
  course: { term: null, modality: null },
  modality: null,
  status: 'synthetic fixture',
};

const syntheticEvent: Recommendation = {
  id: 'demo-event-1',
  kind: 'event',
  title: 'Example USC campus event (synthetic)',
  summary: 'A placeholder event card showing date, access, and registration fields when supplied.',
  why_relevant: ['Could help you learn more and meet people interested in this topic.'],
  benefits: ['Learn from a discussion', 'Meet peers with related interests'],
  prerequisites_or_access: [],
  unknowns: ['This is synthetic fixture data; no date or availability is asserted.'],
  action_url: 'https://example.org/usc-event-demo',
  sources: [{ url: 'https://example.org/usc-event-demo', title: 'Synthetic demo source', checked_at: null }],
  evidence_path: ['Your stated interest', 'Related campus activity', 'Example event'],
  event: { start: null, end: null, timezone: null },
  course: null,
  modality: null,
  status: 'synthetic fixture',
};

export const mockChat: ChatApi['send'] = async (request, signal) => {
  await wait(450, signal);
  const lastUser = [...request.messages].reverse().find((message) => message.role === 'user');
  const userCount = request.messages.filter((message) => message.role === 'user').length;
  const currentText = lastUser?.content.toLowerCase() ?? '';
  const correction = /actually|instead|change|switch|more interested|not that|rather/.test(currentText);

  if (userCount === 1 && /not sure|where to start|interest|curious|explor/.test(currentText)) {
    return response(
      'A good place to start. What kinds of topics or activities make you curious? You can name anything, even if it is not a career goal yet.',
      ['I like solving problems', 'I enjoy helping people', 'I want to build things'],
      [],
    );
  }

  if (userCount === 1 && !correction && /know what|want to do|company|role|team|engineer|designer|doctor/.test(currentText)) {
    return response(
      'Great. What part of that direction interests you most, or what have you already tried? I can use that to make the next suggestions more useful.',
      ['I am new to this area', 'I have tried a project', 'I want to meet people in this field'],
      [],
    );
  }

  const topic = lastUser?.content.trim() || 'your interests';
  const nextMessage = correction
    ? `Thanks for the correction. I’ll use “${topic}” as your current direction. Here are a couple of synthetic examples to show how course and event suggestions will appear.`
    : `Based on what you shared about “${topic}”, here are synthetic examples of the course and event recommendations the connected USC data service can return.`;
  return response(nextMessage, ['I am new to this skill', 'I want to explore a different direction'], [syntheticCourse, syntheticEvent], [
    'Mock mode uses synthetic fixture data only; these are not verified USC offerings.',
  ]);
};

function response(message: string, suggested_replies: string[], recommendations: Recommendation[], limitations: string[] = []): ChatResponse {
  return { message, suggested_replies, recommendations, limitations };
}

function wait(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const timeout = window.setTimeout(resolve, ms);
    signal.addEventListener('abort', () => {
      window.clearTimeout(timeout);
      reject(new DOMException('Request aborted', 'AbortError'));
    }, { once: true });
  });
}
