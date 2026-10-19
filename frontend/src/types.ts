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

export interface UsageBreakdown {
  llm_calls: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  cache_hit_tokens: number;
  cache_miss_tokens: number;
  estimated_cost_usd: number;
  cost_estimate_available?: boolean;
  estimated_cost_cny?: number | null;
  cost_estimate_cny_available?: boolean;
  cache_hit_rate?: number;
  cache_usage_available?: boolean;
  cache_status?: "available" | "unavailable" | "no_calls";
  cache_unavailable_calls?: number;
}

export interface LLMUsage extends UsageBreakdown {
  cache_hit_rate: number;
  currency: string;
  cost_estimate_available: boolean;
  pricing_tiers: string[];
  by_model: Record<string, UsageBreakdown>;
  by_operation: Record<string, UsageBreakdown>;
}

export interface AskResponse {
  answer: string;
  steps: string[];
  sources: SourceResult[];
  collaboration_notes: CollaborationNotes;
  revision_count: number;
  timings: Record<string, number>;
  usage: LLMUsage;
}

export interface WorkflowProgress {
  node: string;
  status: "running" | "completed" | "failed";
  completed_nodes: string[];
  steps: string[];
  revision_count: number;
  elapsed_ms?: number;
  timings: Record<string, number>;
  usage: LLMUsage;
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
