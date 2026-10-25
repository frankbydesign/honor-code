import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { environment } from '../environments/environment';
import { messageFor } from './api/errors';
import { SyncStatus } from './api/models';

const POLL_MS = 2000;
const RETRY_MS = 5000;
/** How often to look for syncs the app ran on its own schedule. */
const IDLE_MS = 60000;

@Injectable({ providedIn: 'root' })
export class SyncService {
  private readonly http = inject(HttpClient);
  private readonly url = `${environment.apiBaseUrl}/sync`;

  private readonly _status = signal<SyncStatus | null>(null);
  private readonly _syncing = signal(false);
  private readonly _error = signal<string | null>(null);
  private readonly _finished = signal(0);
  private timer: ReturnType<typeof setTimeout> | null = null;
  private watching = false;
  private lastRunId: string | null | undefined = undefined;
  private active = true;

  readonly status = this._status.asReadonly();
  readonly syncing = this._syncing.asReadonly();
  readonly error = this._error.asReadonly();
  /** Goes up by one each time a sync this screen watched has ended. */
  readonly finishedCount = this._finished.asReadonly();

  refresh(): void {
    this.active = true;
    this.poll();
  }

  /** Stop checking (signed out). refresh() starts again. */
  stop(): void {
    this.active = false;
    this.clearTimer();
  }

  syncNow(): void {
    this._error.set(null);
    this.http.post(this.url, null, { withCredentials: true }).subscribe({
      next: () => {
        this.watching = true;
        this._syncing.set(true);
        this.poll();
      },
      error: (err: unknown) => {
        if (err instanceof HttpErrorResponse && err.status === 409) {
          this._error.set('A sync is already running');
          this.watching = true;
          this.poll();
          return;
        }
        this._error.set(messageFor(err));
        this._syncing.set(false);
      },
    });
  }

  private poll(): void {
    this.clearTimer();
    this.http.get<SyncStatus>(this.url, { withCredentials: true }).subscribe({
      next: (status) => {
        this._status.set(status);
        const runId = status.last_run?.id ?? null;
        const newRun = this.lastRunId !== undefined && runId !== this.lastRunId;
        this.lastRunId = runId;
        if (status.running) {
          this.watching = true;
          this._syncing.set(true);
          this.schedule(POLL_MS);
          return;
        }
        this._syncing.set(false);
        if (this.watching || newRun) {
          // Ours (Sync now) or the app's own schedule: either way, screens reload.
          this.watching = false;
          this._finished.update((n) => n + 1);
        }
        this.schedule(IDLE_MS);
      },
      error: (err: unknown) => {
        if (this.watching) {
          // A blip mid-sync (API restart, network): keep following it.
          this.schedule(RETRY_MS);
          return;
        }
        this._error.set(messageFor(err));
        this._syncing.set(false);
        this.schedule(IDLE_MS);
      },
    });
  }

  private schedule(ms: number): void {
    if (!this.active) return;
    this.timer = setTimeout(() => this.poll(), ms);
  }

  private clearTimer(): void {
    if (this.timer !== null) {
      clearTimeout(this.timer);
      this.timer = null;
    }
  }
}
