import { Component, computed, inject } from '@angular/core';
import { SyncService } from '../sync.service';

@Component({
  selector: 'app-sync-status',
  template: `
    <div class="sync-status" data-testid="sync-status">
      <span class="sync-text" [class.warn]="isProblem()">{{ text() }}</span>
      <button
        type="button"
        class="small"
        [disabled]="sync.syncing() || !sync.status()?.configured"
        (click)="sync.syncNow()"
      >
        {{ sync.syncing() ? 'Syncing…' : 'Sync now' }}
      </button>
      @if (sync.error()) {
        <span class="error" role="alert">{{ sync.error() }}</span>
      }
    </div>
  `,
})
export class SyncStatusComponent {
  protected readonly sync = inject(SyncService);

  protected readonly isProblem = computed(() => {
    const s = this.sync.status();
    return !!s && (!s.configured || s.last_run?.status === 'failed' || !!s.last_run?.error);
  });

  protected readonly text = computed(() => {
    const s = this.sync.status();
    if (!s) return 'Checking sync…';
    if (!s.configured) return `Sync not configured: set ${s.missing.join(', ')}`;
    if (s.running) return 'Syncing with Fathom…';
    const r = s.last_run;
    if (!r) return 'Not synced yet';
    const when = new Date(r.finished_at ?? r.started_at).toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
    });
    if (r.status === 'failed') return `Last sync failed (${when}): ${r.error ?? 'unknown reason'}`;
    const parts = [`Last sync ${when}`, `${r.meetings_new} new`];
    if (r.meetings_pending) parts.push(`${r.meetings_pending} waiting on Fathom`);
    if (r.extractions_failed) parts.push(`${r.extractions_failed} extraction failed`);
    return parts.join(' · ');
  });
}
