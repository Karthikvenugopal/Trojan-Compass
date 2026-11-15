/** Mirrors the published Recommendation contract in src/trojan_compass/contracts. */
export interface Source {
  url: string;
  title: string;
  checked_at: string | null;
}

export interface EventSchedule {
  start: string | null;
  end: string | null;
  timezone: string | null;
}

export interface CourseDetails {
  term: string | null;
  modality: string | null;
}

export interface Recommendation {
  id: string;
  kind: 'course' | 'event';
  title: string;
  summary: string;
  why_relevant: string[];
  benefits: string[];
  prerequisites_or_access: string[];
  unknowns: string[];
  action_url: string | null;
  sources: Source[];
  evidence_path: string[];
  event: EventSchedule | null;
  course: CourseDetails | null;
  modality: string | null;
  status: string | null;
}

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  edit?: InformationEdit;
}

export type AnswerStatus = 'not_answered' | 'unknown' | 'none' | 'provided';

export interface InformationEdit {
  field: string;
  status: AnswerStatus;
  value: string | null;
}

export interface InformationField extends InformationEdit {
  label: string;
  category: 'fixed' | 'request';
  required: boolean;
}

export interface InformationSnapshot {
  fields: InformationField[];
  ready: boolean;
  missing_fields: string[];
}

/** Stateless API contract specified for POST /api/chat. */
export interface ChatRequest {
  messages: ChatMessage[];
}

export interface ChatResponse {
  message: string;
  suggested_replies: string[];
  recommendations: Recommendation[];
  limitations: string[];
  information?: InformationSnapshot;
  /** Official pages a direct campus/course answer relied on. */
  sources?: Source[];
}

export interface DisplayMessage extends ChatMessage {
  id: string;
  recommendations?: Recommendation[];
  limitations?: string[];
  suggested_replies?: string[];
  sources?: Source[];
}
