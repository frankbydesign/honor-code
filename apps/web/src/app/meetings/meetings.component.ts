import { Component, effect, inject, signal, untracked } from '@angular/core';
import { RouterLink } from '@angular/router';
import { messageFor } from '../api/errors';
import { DocumentSummary } from '../api/models';
import { DocumentsService } from '../documents.service';
import { SyncService } from '../sync.service';

@Component({
  selector: 'app-meetings',
  imports: [RouterLink],
  template: `
    <h2>Meetings</h2>
    @if (error()) {
      <p class="error" role="alert">{{ error() }}</p>
    }
    @if (docs() === null) {
      <p class="muted">Loading…</p>
    } @else if (docs()!.length === 0) {
      <p class="muted empty">No meetings yet. They arrive from Fathom on the next sync.</p>
    } @else {
      <ul class="meeting-list">
        @for (d of docs(); track d.id) {
          <li>
            <a [routerLink]="['/meetings', d.id]">{{ d.title }}</a>
            <span class="muted">{{ d.occurred_on }}</span>
            <span class="counts">
              @if (d.counts.candidate) {
                <span class="pill">{{ d.counts.candidate }} to review</span>
              }
              @if (d.counts.accepted) {
                <span class="pill">{{ d.counts.accepted }} open</span>
              }
              @if (d.counts.done) {
                <span class="pill">{{ d.counts.done }} done</span>
              }
            </span>
          </li>
        }
      </ul>
    }
  `,
})
export class MeetingsComponent {
  private readonly documents = inject(DocumentsService);
  private readonly sync = inject(SyncService);
  protected readonly docs = signal<DocumentSummary[] | null>(null);
  protected readonly error = signal<string | null>(null);

  constructor() {
    effect(() => {
      this.sync.finishedCount();
      untracked(() => this.load());
    });
  }

  private load(): void {
    this.documents.list().subscribe({
      next: (docs) => {
        this.docs.set(docs);
        this.error.set(null);
      },
      error: (err) => {
        this.error.set(messageFor(err));
        if (this.docs() === null) this.docs.set([]);
      },
    });
  }
}
