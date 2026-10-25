import { Component, computed, effect, inject, signal, untracked } from '@angular/core';
import { CommitmentPatch } from '../api/models';
import { CommitmentCardComponent, MoveRequest } from '../commitment-card/commitment-card.component';
import { CommitmentsService, ReviewTab } from '../commitments.service';
import { SyncService } from '../sync.service';

const TABS: { id: ReviewTab; label: string; empty: string }[] = [
  { id: 'candidates', label: 'Candidates', empty: 'Nothing to review. New meetings show up here after a sync.' },
  { id: 'accepted', label: 'Accepted', empty: 'Nothing accepted and open.' },
  { id: 'done', label: 'Done', empty: 'Nothing marked done yet.' },
  { id: 'closed', label: 'Rejected and dropped', empty: 'Nothing rejected or dropped.' },
];

@Component({
  selector: 'app-review',
  imports: [CommitmentCardComponent],
  template: `
    <div class="tabs" role="tablist" aria-label="Commitments by status">
      @for (t of tabs; track t.id) {
        <button
          type="button"
          role="tab"
          [attr.aria-selected]="tab() === t.id"
          [class.active]="tab() === t.id"
          (click)="tab.set(t.id)"
        >
          {{ t.label }} <span class="count">{{ svc.forTab(t.id).length }}</span>
        </button>
      }
    </div>

    @if (svc.error()) {
      <p class="error" role="alert">{{ svc.error() }}</p>
    }

    @if (!svc.loaded()) {
      <p class="muted">Loading…</p>
    } @else if (groups().length === 0) {
      <p class="muted empty">{{ emptyText() }}</p>
    } @else {
      @for (g of groups(); track g.label) {
        <section class="group">
          <h3 data-testid="group-label">{{ g.label }}</h3>
          @for (c of g.items; track c.id) {
            <app-commitment-card
              [commitment]="c"
              [pending]="svc.isPending(c.id)"
              [error]="svc.itemError(c.id)"
              (moved)="move(c.id, $event)"
              (edited)="edit(c.id, $event)"
            />
          }
        </section>
      }
    }
  `,
})
export class ReviewComponent {
  protected readonly svc = inject(CommitmentsService);
  private readonly sync = inject(SyncService);

  protected readonly tabs = TABS;
  protected readonly tab = signal<ReviewTab>('candidates');
  protected readonly groups = computed(() => CommitmentsService.group(this.svc.forTab(this.tab())));
  protected readonly emptyText = computed(() => TABS.find((t) => t.id === this.tab())!.empty);

  constructor() {
    // Load now, and again whenever a sync this app watched has finished.
    effect(() => {
      this.sync.finishedCount();
      untracked(() => this.svc.load());
    });
  }

  protected move(id: string, req: MoveRequest): void {
    void this.svc.transition(id, req.to, req.note);
  }

  protected edit(id: string, patch: CommitmentPatch): void {
    void this.svc.edit(id, patch);
  }
}
