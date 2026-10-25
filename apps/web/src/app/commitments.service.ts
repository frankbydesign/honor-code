import { HttpClient } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { environment } from '../environments/environment';
import { messageFor } from './api/errors';
import { Commitment, CommitmentPatch, CommitmentStatus } from './api/models';

export type ReviewTab = 'candidates' | 'accepted' | 'done' | 'closed';

const TAB_STATUSES: Record<ReviewTab, CommitmentStatus[]> = {
  candidates: ['candidate'],
  accepted: ['accepted'],
  done: ['done'],
  closed: ['rejected', 'dropped'],
};

export interface CommitmentGroup {
  label: string;
  items: Commitment[];
}

export const NO_COUNTERPARTY = 'No one in particular';

@Injectable({ providedIn: 'root' })
export class CommitmentsService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/commitments`;

  private readonly _items = signal<Commitment[]>([]);
  private readonly _loaded = signal(false);
  private readonly _error = signal<string | null>(null);
  private readonly _pending = signal<ReadonlySet<string>>(new Set());
  private readonly _itemErrors = signal<Readonly<Record<string, string>>>({});

  readonly items = this._items.asReadonly();
  readonly loaded = this._loaded.asReadonly();
  readonly error = this._error.asReadonly();

  load(): void {
    this.http.get<Commitment[]>(this.base, { withCredentials: true }).subscribe({
      next: (items) => {
        this._items.set(items);
        this._error.set(null);
        this._loaded.set(true);
      },
      error: (err) => {
        this._error.set(messageFor(err));
        this._loaded.set(true);
      },
    });
  }

  forTab(tab: ReviewTab): Commitment[] {
    const wanted = TAB_STATUSES[tab];
    return this._items().filter((c) => wanted.includes(c.status));
  }

  isPending(id: string): boolean {
    return this._pending().has(id);
  }

  itemError(id: string): string | null {
    return this._itemErrors()[id] ?? null;
  }

  /** Move a commitment. Resolves with the updated row, or null on failure. */
  transition(id: string, to: CommitmentStatus, note?: string): Promise<Commitment | null> {
    const body: { to: CommitmentStatus; note?: string } = { to };
    if (note !== undefined) body.note = note;
    return this.send(id, this.http.post<Commitment>(`${this.base}/${id}/status`, body, { withCredentials: true }));
  }

  edit(id: string, patch: CommitmentPatch): Promise<Commitment | null> {
    return this.send(id, this.http.patch<Commitment>(`${this.base}/${id}`, patch, { withCredentials: true }));
  }

  static group(items: Commitment[]): CommitmentGroup[] {
    const groups = new Map<string, Commitment[]>();
    for (const c of items) {
      const key = c.counterparty?.trim() || '';
      groups.set(key, [...(groups.get(key) ?? []), c]);
    }
    const newestFirst = (a: Commitment, b: Commitment) =>
      (b.document?.occurred_on ?? '').localeCompare(a.document?.occurred_on ?? '') || a.position - b.position;
    return [...groups.entries()]
      .sort(([a], [b]) => (a === '' ? 1 : b === '' ? -1 : a.localeCompare(b)))
      .map(([key, list]) => ({ label: key || NO_COUNTERPARTY, items: [...list].sort(newestFirst) }));
  }

  private async send(id: string, request: ReturnType<HttpClient['post']>): Promise<Commitment | null> {
    this.setPending(id, true);
    this.setItemError(id, null);
    try {
      const updated = (await firstValueFrom(request)) as Commitment;
      this._items.update((list) => list.map((c) => (c.id === id ? updated : c)));
      return updated;
    } catch (err) {
      this.setItemError(id, messageFor(err));
      return null;
    } finally {
      this.setPending(id, false);
    }
  }

  private setPending(id: string, on: boolean): void {
    this._pending.update((s) => {
      const next = new Set(s);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
  }

  private setItemError(id: string, message: string | null): void {
    this._itemErrors.update((m) => {
      const next = { ...m };
      if (message) next[id] = message;
      else delete next[id];
      return next;
    });
  }
}
