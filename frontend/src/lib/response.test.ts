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
