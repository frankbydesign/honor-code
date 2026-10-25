import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { environment } from '../environments/environment';
import { messageFor } from './api/errors';
import { SyncStatus } from './api/models';

const POLL_MS = 2000;

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

  readonly status = this._status.asReadonly();
  readonly syncing = this._syncing.asReadonly();
  readonly error = this._error.asReadonly();
  /** Goes up by one each time a sync this screen watched has ended. */
  readonly finishedCount = this._finished.asReadonly();

  refresh(): void {
    this.poll();
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
        if (status.running) {
          this.watching = true;
          this._syncing.set(true);
          this.timer = setTimeout(() => this.poll(), POLL_MS);
          return;
        }
        this._syncing.set(false);
        if (this.watching) {
          this.watching = false;
          this._finished.update((n) => n + 1);
        }
      },
      error: (err: unknown) => {
        this._error.set(messageFor(err));
        this._syncing.set(false);
        this.watching = false;
      },
    });
  }

  private clearTimer(): void {
    if (this.timer !== null) {
      clearTimeout(this.timer);
      this.timer = null;
    }
  }
}
