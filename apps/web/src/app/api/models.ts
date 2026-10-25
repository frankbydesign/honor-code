// Shapes returned by the API under /api. Kept in step with
// apps/api/app/commitments/schemas.py and apps/api/app/sync/router.py.

export type CommitmentStatus = 'candidate' | 'accepted' | 'rejected' | 'done' | 'dropped';
export type Strength = 'firm' | 'soft' | 'offer';

export interface DocumentRef {
  id: string;
  title: string;
  occurred_on: string;
}

export interface Commitment {
  id: string;
  document_id: string;
  run_id: string;
  status: CommitmentStatus;
  summary: string;
  counterparty: string | null;
  speaker: string | null;
  quote: string;
  quote_found: boolean;
  strength: Strength;
  due_text: string | null;
  due_on: string | null;
  details: string | null;
  position: number;
  created_at: string;
  updated_at: string;
  document?: DocumentRef | null;
}

export type CommitmentPatch = Partial<
  Pick<Commitment, 'summary' | 'counterparty' | 'due_text' | 'due_on' | 'details' | 'strength'>
>;

export interface StatusCounts {
  candidate: number;
  accepted: number;
  done: number;
  rejected: number;
  dropped: number;
}

export interface DocumentSummary {
  id: string;
  kind: string;
  title: string;
  occurred_at: string;
  occurred_on: string;
  source_url: string | null;
  char_count: number;
  counts: StatusCounts;
}

export interface ExtractionRun {
  id: string;
  document_id: string;
  status: 'running' | 'succeeded' | 'failed';
  model: string;
  prompt_version: string;
  my_speaker: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  started_at: string;
  finished_at: string | null;
  error: string | null;
}

export interface VendorActionItem {
  description: string;
  completed?: boolean | null;
  recording_timestamp?: string | null;
  assignee?: { name?: string | null; email?: string | null } | null;
}

export interface DocumentDetail extends DocumentSummary {
  raw_text: string;
  speakers: string[];
  my_speaker: string | null;
  recorded_by_name: string | null;
  recorded_by_email: string | null;
  vendor_action_items: VendorActionItem[] | null;
  runs: ExtractionRun[];
  commitments: Commitment[];
}

export interface SyncRun {
  id: string;
  trigger: string;
  status: 'running' | 'succeeded' | 'failed';
  window_start: string;
  started_at: string;
  finished_at: string | null;
  meetings_seen: number;
  meetings_new: number;
  meetings_pending: number;
  extractions_ok: number;
  extractions_failed: number;
  error: string | null;
}

export interface SyncStatus {
  configured: boolean;
  missing: string[];
  running: boolean;
  last_run: SyncRun | null;
}
