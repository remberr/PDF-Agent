export interface HealthResponse {
  status: string;
  service: string;
}

export interface SessionDetail {
  session_id: string;
  loaded_pdfs: string[];
  message_count: number;
  has_vectorstore: boolean;
  total_documents: number;
}

export interface UploadResponse {
  session_id: string;
  uploaded_files: string[];
  loaded_pdfs: string[];
  total_documents: number;
}

export interface SourceResult {
  citation_id: string;
  source: string;
  page: number;
  excerpt: string;
}

export interface CollaborationNotes {
  agent?: string;
  status?: string;
  answer?: string;
  issues?: string[];
  missing_information?: string[];
  recommendations?: string[];
  needs_revision?: boolean;
  next_steps?: string[];
}

export interface AskResponse {
  answer: string;
  steps: string[];
  sources: SourceResult[];
  collaboration_notes: CollaborationNotes;
  revision_count: number;
  timings: Record<string, number>;
}

export interface WorkflowProgress {
  node: string;
  status: "running" | "completed" | "failed";
  completed_nodes: string[];
  steps: string[];
  revision_count: number;
  elapsed_ms?: number;
  timings: Record<string, number>;
}

export interface ConversationTurn {
  id: string;
  question: string;
  result?: AskResponse;
  error?: string;
  pending: boolean;
}

export type BackendStatus = "checking" | "online" | "offline";
export type MobileView = "documents" | "chat" | "workflow";
export type Language = "en" | "zh";
