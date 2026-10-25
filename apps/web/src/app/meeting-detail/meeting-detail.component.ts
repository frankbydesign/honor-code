import { Component, effect, inject, input, signal, untracked } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { messageFor } from '../api/errors';
import { CommitmentPatch, DocumentDetail } from '../api/models';
import { CommitmentCardComponent, MoveRequest } from '../commitment-card/commitment-card.component';
import { CommitmentsService } from '../commitments.service';
import { DocumentsService } from '../documents.service';

type Confirming = 'extract' | 'remove' | null;

@Component({
  selector: 'app-meeting-detail',
  imports: [RouterLink, CommitmentCardComponent],
  template: `
    <p><a routerLink="/meetings">← Meetings</a></p>

    @if (loadError()) {
      <p class="error" role="alert">{{ loadError() }}</p>
    }
    @if (actionError()) {
      <p class="error" role="alert">{{ actionError() }}</p>
    }

    @if (doc(); as d) {
      <header class="detail-header">
        <h2>{{ d.title }}</h2>
        <p class="muted">
          {{ d.occurred_on }}
          @if (d.my_speaker) {
            · you are “{{ d.my_speaker }}”
          } @else {
            · your speaker label was not matched
          }
          @if (d.source_url) {
            · <a [href]="d.source_url" target="_blank" rel="noopener noreferrer">Open in Fathom</a>
          }
        </p>
      </header>

      <div class="detail-actions">
        @switch (confirming()) {
          @case ('extract') {
            <span>Run extraction again? Existing commitments stay; new candidates are added.</span>
            <button type="button" class="primary" [disabled]="busy()" (click)="extract()">Yes, re-extract</button>
            <button type="button" (click)="confirming.set(null)">Cancel</button>
          }
          @case ('remove') {
            <span>Remove this meeting and its commitments? Later syncs will not bring it back.</span>
            <button type="button" class="danger" [disabled]="busy()" (click)="remove()">Yes, remove</button>
            <button type="button" (click)="confirming.set(null)">Cancel</button>
          }
          @default {
            <button type="button" [disabled]="busy()" (click)="confirming.set('extract')">Re-extract</button>
            <button type="button" [disabled]="busy()" (click)="confirming.set('remove')">Remove</button>
          }
        }
      </div>

      <section>
        <h3>Commitments</h3>
        @for (c of d.commitments; track c.id) {
          <app-commitment-card
            [commitment]="c"
            [showMeeting]="false"
            [pending]="commitments.isPending(c.id)"
            [error]="commitments.itemError(c.id)"
            (moved)="move(c.id, $event)"
            (edited)="edit(c.id, $event)"
          />
        } @empty {
          <p class="muted">No commitments found in this meeting.</p>
        }
      </section>

      @if (d.vendor_action_items?.length) {
        <section>
          <h3>Fathom's action items</h3>
          <p class="muted">For comparison only; these are not tracked here.</p>
          <ul>
            @for (a of d.vendor_action_items; track $index) {
              <li>
                {{ a.description }}
                @if (a.assignee?.name) {
                  <span class="muted">· {{ a.assignee?.name }}</span>
                }
              </li>
            }
          </ul>
        </section>
      }

      <section>
        <h3>Extraction runs</h3>
        <ul class="runs">
          @for (r of d.runs; track r.id) {
            <li>
              <span class="run-status" [attr.data-status]="r.status">{{ r.status }}</span>
              {{ r.started_at.slice(0, 16).replace('T', ' ') }} UTC · {{ r.model }} · prompt {{ r.prompt_version }}
              @if (r.input_tokens !== null) {
                · {{ r.input_tokens }} in / {{ r.output_tokens }} out
              }
              @if (r.error) {
                <div class="muted">{{ r.error }}</div>
              }
            </li>
          } @empty {
            <li class="muted">Not extracted yet.</li>
          }
        </ul>
      </section>

      <details class="transcript">
        <summary>Transcript ({{ d.char_count }} characters)</summary>
        <pre>{{ d.raw_text }}</pre>
      </details>
    } @else if (!loadError()) {
      <p class="muted">Loading…</p>
    }
  `,
})
export class MeetingDetailComponent {
  readonly id = input.required<string>();

  private readonly documents = inject(DocumentsService);
  protected readonly commitments = inject(CommitmentsService);
  private readonly router = inject(Router);

  protected readonly doc = signal<DocumentDetail | null>(null);
  protected readonly loadError = signal<string | null>(null);
  protected readonly actionError = signal<string | null>(null);
  protected readonly confirming = signal<Confirming>(null);
  protected readonly busy = signal(false);

  constructor() {
    effect(() => {
      const id = this.id();
      untracked(() => this.load(id));
    });
  }

  private load(id: string): void {
    this.documents.get(id).subscribe({
      next: (d) => {
        this.doc.set(d);
        this.loadError.set(null);
      },
      error: (err) => this.loadError.set(messageFor(err)),
    });
  }

  protected extract(): void {
    this.busy.set(true);
    this.actionError.set(null);
    this.documents.extract(this.id()).subscribe({
      next: () => this.afterAction(),
      error: (err) => {
        this.actionError.set(messageFor(err));
        this.afterAction();
      },
    });
  }

  protected remove(): void {
    this.busy.set(true);
    this.actionError.set(null);
    this.documents.remove(this.id()).subscribe({
      next: () => {
        this.busy.set(false);
        void this.router.navigateByUrl('/meetings');
      },
      error: (err) => {
        this.actionError.set(messageFor(err));
        this.busy.set(false);
        this.confirming.set(null);
      },
    });
  }

  protected async move(id: string, req: MoveRequest): Promise<void> {
    if (await this.commitments.transition(id, req.to, req.note)) this.load(this.id());
  }

  protected async edit(id: string, patch: CommitmentPatch): Promise<void> {
    if (await this.commitments.edit(id, patch)) this.load(this.id());
  }

  private afterAction(): void {
    this.busy.set(false);
    this.confirming.set(null);
    this.load(this.id());
  }
}
