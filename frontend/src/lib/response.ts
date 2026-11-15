import { ChatApiError } from './api';
import type { ChatResponse, Recommendation } from '../types';

/** Validate untrusted HTTP data before React renders nested recommendation fields. */
export function decodeResponse(value: unknown): ChatResponse {
  if (!record(value) || !text(value.message) || !strings(value.suggested_replies)
      || !strings(value.limitations) || !Array.isArray(value.recommendations)
      || !value.recommendations.every(recommendation)
      || (value.information !== undefined && !information(value.information))
      || (value.sources !== undefined && !sources(value.sources))
      || (value.graph != null && !graph(value.graph))
      || (value.roadmap != null && !roadmap(value.roadmap))) {
    throw new ChatApiError('The server returned an unreadable response. Your message is still here; please retry.', 502);
  }
  return value as unknown as ChatResponse;
}

function sources(value: unknown): boolean {
  return Array.isArray(value) && value.length <= 5 && value.every(source => record(source)
    && url(source.url) && text(source.title) && nullableText(source.checked_at ?? null));
}

function optionalUrl(value: unknown): boolean { return value == null || url(value); }
function optionalText(value: unknown): boolean { return value == null || text(value); }

/** Graph labels and links are rendered, so reject anything that is not text or http(s). */
function graph(value: unknown): boolean {
  if (!record(value) || !Array.isArray(value.nodes) || !Array.isArray(value.edges)
      || value.nodes.length > 80 || value.edges.length > 200) return false;
  const kinds = ['interest', 'skill', 'course', 'professor', 'event'];
  return value.nodes.every(node => record(node) && text(node.id) && text(node.label)
      && kinds.includes(String(node.kind)) && optionalText(node.detail) && optionalUrl(node.url))
    && value.edges.every(edge => record(edge) && text(edge.source) && text(edge.target) && text(edge.label));
}

function roadmap(value: unknown): boolean {
  if (!record(value) || !text(value.focus) || !strings(value.known)) return false;
  const lists = ['to_learn', 'courses', 'people', 'events'];
  if (!lists.every(key => Array.isArray(value[key]) && (value[key] as unknown[]).every(record))) return false;
  const items = (key: string) => value[key] as Record<string, unknown>[];
  return items('to_learn').every(item => text(item.name) && optionalText(item.why))
    && items('courses').every(item => text(item.code) && text(item.title) && optionalText(item.term)
      && optionalText(item.note) && optionalUrl(item.url))
    && items('people').every(item => text(item.name) && optionalText(item.role)
      && optionalText(item.research) && optionalUrl(item.url))
    && items('events').every(item => text(item.title) && optionalText(item.when) && optionalUrl(item.url));
}

function information(value: unknown): boolean {
  if (!record(value) || typeof value.ready !== 'boolean'
      || !Array.isArray(value.missing_fields) || !value.missing_fields.every(fieldKey)
      || !Array.isArray(value.fields) || value.fields.length > 40) return false;
  const keys = new Set<string>();
  return value.fields.every(field => {
    if (!record(field) || !fieldKey(field.field) || keys.has(field.field)
        || !text(field.label) || typeof field.required !== 'boolean'
        || !['fixed', 'request'].includes(String(field.category))
        || !['not_answered', 'unknown', 'none', 'provided'].includes(String(field.status))) return false;
    keys.add(field.field);
    return field.status === 'provided'
      ? text(field.value) && field.value.length <= 1000 : field.value === null;
  });
}

function fieldKey(value: unknown): value is string {
  return typeof value === 'string' && value.length <= 120
    && /^(direction|direction_detail|background|program|preferences|time_window|modality|target|skills\..{1,100})$/.test(value);
}

function recommendation(value: unknown): value is Recommendation {
  if (!record(value) || !text(value.id) || !text(value.title) || !text(value.summary)
      || (value.kind !== 'course' && value.kind !== 'event')) return false;
  for (const field of ['why_relevant', 'benefits', 'prerequisites_or_access', 'unknowns', 'evidence_path']) {
    if (!strings(value[field])) return false;
  }
  if (!Array.isArray(value.evidence_path) || value.evidence_path.length === 0
      || !Array.isArray(value.sources) || value.sources.length === 0
      || !value.sources.every(source => record(source) && url(source.url)
        && text(source.title) && nullableText(source.checked_at))) return false;
  if (value.action_url !== null && !url(value.action_url)) return false;
  if (!nullableText(value.modality) || !nullableText(value.status)) return false;
  if (value.event !== null && (!record(value.event) || !nullableText(value.event.start)
      || !nullableText(value.event.end) || !nullableText(value.event.timezone))) return false;
  if (value.course !== null && (!record(value.course) || !nullableText(value.course.term)
      || !nullableText(value.course.modality))) return false;
  return true;
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}
function text(value: unknown): value is string { return typeof value === 'string' && value.trim().length > 0; }
function nullableText(value: unknown): value is string | null { return value === null || text(value); }
function strings(value: unknown): value is string[] { return Array.isArray(value) && value.every(text); }
function url(value: unknown): value is string {
  if (typeof value !== 'string') return false;
  try { return ['http:', 'https:'].includes(new URL(value).protocol); } catch { return false; }
}
