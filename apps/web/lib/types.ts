export type User = {
  id: string;
  email: string;
  display_name: string;
  timezone: string;
  preferred_language: string;
  response_style: string;
  memory_enabled: boolean;
  email_verified: boolean;
};

export type Conversation = {
  id: string;
  title: string;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
};

export type Citation = {
  marker: string;
  type: "document" | "memory";
  document_id?: string;
  chunk_id?: string;
  memory_id?: string;
  label?: string;
  filename?: string;
  page_start?: number | null;
  section?: string | null;
  excerpt?: string;
  source?: string;
};

export type ChatMessage = {
  id: string;
  conversation_id: string;
  role: "user" | "assistant" | "tool";
  content: string;
  status: "streaming" | "completed" | "failed" | "incomplete";
  citations: Citation[];
  evidence: Citation[];
  actions: Array<Record<string, string>>;
  diagnostics: Record<string, unknown>;
  error_code: string | null;
  created_at: string;
};

export type DocumentItem = {
  id: string;
  filename: string;
  label: string;
  mime_type: string;
  extension: string;
  size_bytes: number;
  status: string;
  error_code: string | null;
  error_message: string | null;
  page_count: number | null;
  chunk_count: number;
  cancel_requested: boolean;
  created_at: string;
  updated_at: string;
};

export type MemoryItem = {
  id: string;
  content: string;
  source: string;
  status: string;
  conflict_with_id: string | null;
  version: number;
  created_at: string;
  updated_at: string;
};

export type TaskItem = {
  id: string;
  title: string;
  description: string;
  due_date: string | null;
  due_label: string | null;
  priority: string | null;
  status: string;
  source_type: string | null;
  source_id: string | null;
  source_excerpt: string | null;
  confidence: number | null;
  duplicate?: boolean;
  created_at: string;
  updated_at: string;
};

export type Dashboard = {
  user: User;
  counts: { documents: number; conversations: number; memories: number; open_tasks: number };
  recent_conversations: Conversation[];
  documents: DocumentItem[];
  processing: DocumentItem[];
  memories: MemoryItem[];
  pending_tasks: TaskItem[];
  activity: Array<{ id: string; action: string; summary: string; created_at: string }>;
};
