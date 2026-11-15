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
  graph?: PathwayGraph | null;
  roadmap?: Roadmap | null;
}

export interface DisplayMessage extends ChatMessage {
  id: string;
  recommendations?: Recommendation[];
  limitations?: string[];
  suggested_replies?: string[];
  sources?: Source[];
}

/** Knowledge-graph pathway returned with recommendations (shared campus data). */
export type GraphNodeKind = 'interest' | 'skill' | 'course' | 'professor' | 'event';

export interface GraphNode {
  id: string;
  kind: GraphNodeKind;
  label: string;
  detail: string | null;
  url: string | null;
  state: 'known' | 'to_learn' | 'recommended' | 'prerequisite' | 'related' | null;
}

export interface GraphEdge {
  source: string;
  target: string;
  label: string;
  inferred: boolean;
}

export interface PathwayGraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface Roadmap {
  focus: string;
  known: string[];
  to_learn: { name: string; why: string | null }[];
  courses: { code: string; title: string; term: string | null; note: string | null; url: string | null }[];
  people: { name: string; role: string | null; research: string | null; url: string | null }[];
  events: { title: string; when: string | null; url: string | null }[];
}

export interface Pathway {
  graph: PathwayGraph | null;
  roadmap: Roadmap | null;
}
