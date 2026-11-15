import { describe, expect, it } from 'vitest';
import { decodeResponse } from './response';

function response(recommendations: unknown[] = []): unknown {
  return { message: 'Synthetic response', suggested_replies: [], limitations: [], recommendations };
}

describe('response validation', () => {
  it('accepts an empty grounded result', () => {
    expect(decodeResponse(response()).recommendations).toEqual([]);
  });
  it.each([null, {}, { why_relevant: 'not a list' }])('rejects malformed card data', value => {
    expect(() => decodeResponse(response([value]))).toThrow('unreadable response');
  });
  it('rejects non-text suggested replies before React renders them', () => {
    expect(() => decodeResponse({ message: 'Synthetic', suggested_replies: [{}], recommendations: [], limitations: [] })).toThrow();
  });
});

const validCard = {
  id: 'fixture', kind: 'course', title: 'Synthetic course', summary: 'Synthetic summary',
  why_relevant: [], benefits: [], prerequisites_or_access: [], unknowns: [],
  action_url: 'https://example.org/course',
  sources: [{ url: 'https://example.org/source', title: 'Synthetic source', checked_at: null }],
  evidence_path: ['Synthetic topic', 'Synthetic course'],
  course: null, event: null, modality: null, status: null,
};

it('accepts a complete recommendation with nullable structured fields', () => {
  expect(decodeResponse(response([validCard])).recommendations[0]?.id).toBe('fixture');
});

it.each([
  { why_relevant: {} }, { sources: [null] }, { event: { start: 42 } },
  { action_url: 'javascript:alert(1)' },
  { sources: [{ url: 'javascript:alert(1)', title: 'Unsafe', checked_at: null }] },
])('rejects unsafe or unrenderable nested card fields', patch => {
  expect(() => decodeResponse(response([{ ...validCard, ...patch }]))).toThrow('unreadable response');
});

it.each([
  { field: 'direction', status: 'provided', value: null },
  { field: 'direction', status: 'none', value: 'invented' },
  { field: 'unsupported', status: 'unknown', value: null },
])('rejects malformed information snapshots', patch => {
  expect(() => decodeResponse({ message: 'Synthetic', suggested_replies: [], limitations: [], recommendations: [],
    information: { ready: true, missing_fields: [], fields: [
      { label: 'Synthetic field', category: 'fixed', required: true, ...patch },
    ] },
  })).toThrow('unreadable response');
});

it.each([[{ code: 'PSYC 100', title: 'Psychology', sources: [] }],
  [{ code: 'PSYC 100', title: 'Psychology', sources: [{ url: 'javascript:alert(1)', title: 'Bad', checked_at: null }] }],
  [null]])('rejects malformed course-history choices', course_history_options => {
  expect(() => decodeResponse({ message: 'Synthetic', suggested_replies: [], recommendations: [], limitations: [], course_history_options })).toThrow();
});

it('accepts answer sources and rejects unsafe source links', () => {
  const source = { url: 'https://libraries.usc.edu/hours', title: 'Library Hours', checked_at: null };
  expect(decodeResponse({ ...(response() as object), sources: [source] }).sources?.[0]?.title).toBe('Library Hours');
  expect(() => decodeResponse({ ...(response() as object),
    sources: [{ ...source, url: 'javascript:alert(1)' }] })).toThrow('unreadable response');
});

it('rejects unsafe guidance action sources before rendering the roadmap', () => {
  expect(() => decodeResponse({ message: 'Synthetic', suggested_replies: [], recommendations: [], limitations: [],
    guidance: { mode: 'plan', goal: 'Synthetic', headline: 'Plan', suggested_paths: [], skills: [], steps: [], next_question: null, limitations: [], actions: [
      { id: 'unsafe', kind: 'faculty', title: 'Synthetic', summary: 'Synthetic', why_relevant: 'Synthetic', skill_names: [], url: 'javascript:alert(1)', sources: [], availability: 'unknown', checks: [], term: null },
    ] } })).toThrow('unreadable response');
});
