export type BoostField = {
  key: string;
  label: string;
  column?: "document_number" | "document_version";
  required?: boolean;
  multiline?: boolean;
  type?: "month";
  fixed_lines?: string[];
  placeholder?: string;
};

export type BoostConfig = {
  available: boolean;
  template_id: string | null;
  template_version: string | null;
  template_status: string | null;
  fields: BoostField[];
  input_template_available: boolean;
};

export type ParseIssue = { severity: "error" | "warning"; code: string; message: string; sheet: string; cell: string };

export type SourceImage = { id: string; url: string; px_w: number; px_h: number; sha256: string };

export type SourceTableCell = { text: string; col: number; col_span: number; row_span: number; images: SourceImage[] };

export type SourceItem =
  | { type: "heading"; level: number; text: string; src: string }
  | { type: "paragraph"; kind: "body" | "note"; text: string; src: string }
  | { type: "list"; style: "decimal" | "letter" | "bullet"; continues?: boolean; src: string; items: Array<{ text: string; level: number; src: string }> }
  | { type: "table"; col_widths: number[]; header_rows: number; src: string; rows: SourceTableCell[][] }
  | { type: "image"; ref: SourceImage; src: string };

export type SourceDocument = {
  parser_version: string;
  revision_history: string[];
  chapters: Array<{ title: string; sheet: string; items: SourceItem[] }>;
};

export type SourceFileSummary = {
  id: string;
  status: "parsed" | "invalid";
  original_filename: string;
  size_bytes: number;
  parser_version: string;
  created_at: string | null;
  chapter_count?: number;
  heading_count?: number;
  table_count?: number;
  image_count?: number;
  error_count: number;
  warning_count: number;
};

export type SourceFile = SourceFileSummary & { issues: ParseIssue[]; document: SourceDocument | null };

export type BoostProject = {
  id: string;
  product_type: "boost-integrated-unit";
  name: string;
  description: string;
  document_number: string;
  document_version: string;
  fields: Record<string, string>;
  status: string;
  revision: number;
  source_file: SourceFileSummary | null;
  created_at: string;
  updated_at: string;
};

export type BoostPreflight = {
  ready: boolean;
  blockers: Array<{ code: string; message: string }>;
  warnings: Array<{ code: string; message: string }>;
  stats: Record<string, number>;
  warning_confirmation_required: boolean;
};

export type BoostTask = {
  id: string;
  status: string;
  phase: string;
  progress_percent: number;
  progress_message: string;
  heartbeat_at?: string;
  started_at?: string;
  completed_at?: string;
  created_at: string;
  elapsed_seconds: number;
  stalled: boolean;
  attempts: number;
  diagnostics: Record<string, unknown>;
  error_code?: string;
  error_detail?: string;
  events: Array<{ phase: string; progress_percent: number; message: string; created_at: string }>;
};

export type BoostDocumentRecord = { id: string; task_id: string; file_sha256: string; created_at: string; download_url: string };
