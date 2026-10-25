// Test data builders shared by the specs. Not imported by app code.
import { Commitment, DocumentDetail, DocumentSummary, SyncStatus } from './api/models';

export function makeCommitment(overrides: Partial<Commitment> = {}): Commitment {
  return {
    id: 'c-1',
    document_id: 'doc-1',
    run_id: 'run-1',
    status: 'candidate',
    summary: 'Send Alice the revised budget',
    counterparty: 'Alice Kim',
    speaker: 'Frank E.',
    quote: "I'll send you the revised budget by Thursday.",
    quote_found: true,
    strength: 'firm',
    due_text: 'by Thursday',
    due_on: '2026-10-22',
    details: null,
    position: 0,
    created_at: '2026-10-21T04:05:00Z',
    updated_at: '2026-10-21T04:05:00Z',
    document: { id: 'doc-1', title: 'Budget check-in', occurred_on: '2026-10-20' },
    ...overrides,
  };
}

export function makeDocumentSummary(overrides: Partial<DocumentSummary> = {}): DocumentSummary {
  return {
    id: 'doc-1',
    kind: 'fathom_meeting',
    title: 'Budget check-in',
    occurred_at: '2026-10-21T03:30:00Z',
    occurred_on: '2026-10-20',
    source_url: 'https://fathom.video/share/invented',
    char_count: 320,
    counts: { candidate: 1, accepted: 0, done: 0, rejected: 0, dropped: 0 },
    ...overrides,
  };
}

export function makeDocumentDetail(overrides: Partial<DocumentDetail> = {}): DocumentDetail {
  return {
    ...makeDocumentSummary(),
    raw_text: "[00:00:11] Frank E.: I'll send you the revised budget by Thursday.",
    speakers: ['Alice Kim', 'Frank E.'],
    my_speaker: 'Frank E.',
    recorded_by_name: 'Frank Example',
    recorded_by_email: 'frank@example.com',
    vendor_action_items: null,
    runs: [
      {
        id: 'run-1',
        document_id: 'doc-1',
        status: 'succeeded',
        model: 'claude-sonnet-5-5',
        prompt_version: 'v1',
        my_speaker: 'Frank E.',
        input_tokens: 1200,
        output_tokens: 150,
        started_at: '2026-10-21T04:05:00Z',
        finished_at: '2026-10-21T04:05:09Z',
        error: null,
      },
    ],
    commitments: [makeCommitment()],
    ...overrides,
  };
}

export function makeSyncStatus(overrides: Partial<SyncStatus> = {}): SyncStatus {
  return { configured: true, missing: [], running: false, last_run: null, ...overrides };
}
