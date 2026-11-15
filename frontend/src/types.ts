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
  asked_field?: string | null;
  shown_resources?: ShownResource[];
}

export interface ShownResource {
  id: string;
  title: string;
  kind: 'course' | 'event' | 'faculty' | 'research';
  section: 'plan' | 'recommendations';
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

export interface CourseHistoryOption {
  code: string;
  title: string;
  sources: Source[];
}

export interface ChatResponse {
  asked_field?: string | null;
  guidance?: CareerGuidance | null;
  course_history_options?: CourseHistoryOption[];
  message: string;
  suggested_replies: string[];
  recommendations: Recommendation[];
  limitations: string[];
  information?: InformationSnapshot;
  /** Official pages a direct campus/course answer relied on. */
  sources?: Source[];
}

export interface DisplayMessage extends ChatMessage {
  guidance?: CareerGuidance | null;
  id: string;
  course_history_options?: CourseHistoryOption[];
  recommendations?: Recommendation[];
  limitations?: string[];
  suggested_replies?: string[];
  sources?: Source[];
}

export interface CareerOption { id: string; title: string; why_consider: string; select_message: string; sources: Source[]; }
export interface CareerSkill {
  name: string; status: 'known' | 'learning' | 'not_yet_learned' | 'unknown';
  category: 'skill' | 'knowledge'; basis: string;
  student_evidence: { message_index: number; quote: string }[]; sources: Source[];
}
export interface GuidanceAction {
  id: string; kind: 'course' | 'event' | 'faculty' | 'research'; title: string; summary: string;
  why_relevant: string; skill_names: string[]; url: string; sources: Source[];
  availability: 'unknown' | 'snapshot'; checks: string[]; term: string | null;
}
export interface CareerGuidance {
  mode: 'explore' | 'plan' | 'coverage_gap'; goal: string | null; headline: string;
  suggested_paths: CareerOption[]; skills: CareerSkill[]; actions: GuidanceAction[];
  steps: { id: string; title: string; description: string; skill_names: string[]; action_ids: string[]; depends_on: string[] }[];
  next_question: { text: string; options: string[]; requested_fields: string[]; reason: string } | null;
  limitations: string[];
}
