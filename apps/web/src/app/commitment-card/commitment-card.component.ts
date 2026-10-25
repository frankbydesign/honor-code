import { Component, computed, input, output, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { Commitment, CommitmentPatch, CommitmentStatus } from '../api/models';
import { EditableTextComponent } from '../editable-text/editable-text.component';

export interface MoveRequest {
  to: CommitmentStatus;
  note?: string;
}

const STRENGTH_LABEL = { firm: 'Firm', soft: 'Soft', offer: 'Offer' } as const;

@Component({
  selector: 'app-commitment-card',
  imports: [RouterLink, EditableTextComponent],
  template: `
    @let c = commitment();
    <article class="card" data-testid="commitment-card" [class.closed]="!editable()">
      <div class="card-top">
        <span class="badge" [attr.data-strength]="c.strength">{{ strengthLabel() }}</span>
        @if (showMeeting() && c.document) {
          <a class="meeting-link" [routerLink]="['/meetings', c.document.id]">
            {{ c.document.title }} · {{ c.document.occurred_on }}
          </a>
        }
      </div>

      <p class="summary">
        <app-editable-text
          label="summary"
          [value]="c.summary"
          [required]="true"
          [enabled]="editable() && !pending()"
          (saved)="emitEdit({ summary: $event ?? c.summary })"
        />
      </p>

      <dl class="facts">
        <dt>For</dt>
        <dd>
          <app-editable-text
            label="who it is for"
            placeholder="no one in particular"
            [value]="c.counterparty"
            [enabled]="editable() && !pending()"
            (saved)="emitEdit({ counterparty: $event })"
          />
        </dd>
        <dt>When</dt>
        <dd>
          <app-editable-text
            label="when"
            placeholder="no date said"
            [value]="c.due_text"
            [enabled]="editable() && !pending()"
            (saved)="emitEdit({ due_text: $event })"
          />
          @if (c.due_on) {
            <span class="muted"> ({{ c.due_on }})</span>
          }
        </dd>
      </dl>

      <details class="quote">
        <summary>
          What you said
          @if (!c.quote_found) {
            <span class="warn">· not found verbatim in the transcript</span>
          }
        </summary>
        <blockquote>{{ c.quote }}</blockquote>
        @if (c.details) {
          <p class="muted">{{ c.details }}</p>
        }
      </details>

      <div class="card-actions" data-testid="card-actions">
        @for (action of actions(); track action.to) {
          <button
            type="button"
            [class.primary]="action.primary"
            [disabled]="pending()"
            (click)="onAction(action.to)"
          >
            {{ action.label }}
          </button>
        }
      </div>

      @if (droppingNote()) {
        <div class="drop-note">
          <label>
            Why drop it? (optional)
            <input #note type="text" (keydown.enter)="confirmDrop(note.value)" />
          </label>
          <button type="button" [disabled]="pending()" (click)="confirmDrop(note.value)">Confirm drop</button>
          <button type="button" (click)="droppingNote.set(false)">Cancel</button>
        </div>
      }

      @if (error()) {
        <p class="error" role="alert">{{ error() }}</p>
      }
    </article>
  `,
})
export class CommitmentCardComponent {
  readonly commitment = input.required<Commitment>();
  readonly pending = input(false);
  readonly error = input<string | null>(null);
  readonly showMeeting = input(true);
  readonly moved = output<MoveRequest>();
  readonly edited = output<CommitmentPatch>();

  protected readonly droppingNote = signal(false);
  protected readonly strengthLabel = computed(() => STRENGTH_LABEL[this.commitment().strength] ?? this.commitment().strength);
  protected readonly editable = computed(() => ['candidate', 'accepted'].includes(this.commitment().status));

  protected readonly actions = computed(() => {
    switch (this.commitment().status) {
      case 'candidate':
        return [
          { label: 'Accept', to: 'accepted' as const, primary: true },
          { label: 'Reject', to: 'rejected' as const, primary: false },
        ];
      case 'accepted':
        return [
          { label: 'Done', to: 'done' as const, primary: true },
          { label: 'Drop', to: 'dropped' as const, primary: false },
        ];
      case 'done':
        return [{ label: 'Reopen', to: 'accepted' as const, primary: false }];
      case 'rejected':
        return [{ label: 'Restore', to: 'candidate' as const, primary: false }];
      case 'dropped':
        return [{ label: 'Restore', to: 'accepted' as const, primary: false }];
    }
  });

  protected onAction(to: CommitmentStatus): void {
    if (to === 'dropped') {
      this.droppingNote.set(true);
      return;
    }
    this.moved.emit({ to });
  }

  protected confirmDrop(note: string): void {
    this.droppingNote.set(false);
    const trimmed = note.trim();
    this.moved.emit(trimmed ? { to: 'dropped', note: trimmed } : { to: 'dropped' });
  }

  protected emitEdit(patch: CommitmentPatch): void {
    this.edited.emit(patch);
  }
}
