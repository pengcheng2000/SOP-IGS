export type User = { id: string; display_name: string; role: string; csrf_token?: string };

export type Project = {
  id: string;
  name: string;
  description: string;
  document_number: string;
  document_title: string;
  document_version: string;
  product_phase: string;
  test_period: string;
  test_location: string;
  testers: string;
  product_model: string;
  product_serial_no: string;
  product_info: string;
  project_differences: string;
  status: string;
  revision: number;
  selected_test_item_ids: string[];
  display_numbers: Record<string, string>;
  photo_count: number;
  created_at: string;
  updated_at: string;
};

export type TreeItem = {
  id: string;
  title: string;
  node_type: "GROUP" | "LEAF";
  state: "checked" | "unchecked" | "indeterminate";
  display_number?: string;
  included: boolean;
  children: TreeItem[];
};

export type Photo = {
  id: string;
  photo_group_id: string;
  test_item_id: string | null;
  original_filename: string;
  mime_type: string;
  width?: number;
  height?: number;
  caption: string;
  sort_order: number;
  status: string;
  error_code?: string;
  error_detail?: string;
  preview_url: string;
};

export type PhotoGroup = {
  id: string;
  project_id: string;
  test_item_id: string | null;
  scope: "test_item" | "sample";
  template_group_id?: string;
  key: string;
  title: string;
  sort_order: number;
  source: "template" | "custom";
  requiredness: "required" | "recommended" | "optional";
  min_photos: number;
  layout_profile: string;
  preferred_columns?: number;
  hint: string;
  photo_count: number;
};

export type GroupCompleteness = {
  photo_group_id: string;
  test_item_id: string | null;
  scope: "test_item" | "sample";
  key: string;
  title: string;
  requiredness: "required" | "recommended" | "optional";
  min_photos: number;
  photo_count: number;
  complete: boolean;
};

export type Preflight = {
  ready: boolean;
  blockers: Array<{ code: string; message: string; photo_groups?: GroupCompleteness[] }>;
  warnings: Array<{ code: string; message: string; test_item_ids?: string[]; photo_groups?: GroupCompleteness[] }>;
  selected_count: number;
  photo_count: number;
  without_photos: string[];
  group_completeness: GroupCompleteness[];
  sample_group_completeness: GroupCompleteness[];
  warning_confirmation_required: boolean;
};

export type TaskEvent = {
  phase: string;
  progress_percent: number;
  message: string;
  details: Record<string, unknown>;
  created_at: string;
};

export type GenerationTask = {
  id: string;
  status: string;
  phase: string;
  progress_percent: number;
  progress_message: string;
  heartbeat_at?: string;
  phase_started_at?: string;
  started_at?: string;
  completed_at?: string;
  created_at: string;
  updated_at: string;
  elapsed_seconds: number;
  phase_elapsed_seconds: number;
  stalled: boolean;
  diagnostics: Record<string, unknown>;
  attempts: number;
  error_code?: string;
  error_detail?: string;
  events: TaskEvent[];
};
