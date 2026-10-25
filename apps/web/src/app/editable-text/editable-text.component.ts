import { Component, ElementRef, input, output, signal, viewChild } from '@angular/core';

/**
 * A value shown as text with an Edit button. Edit turns it into an input;
 * Enter or Save emits the new value, Escape or Cancel puts it back.
 * Emits null when an optional field is cleared.
 */
@Component({
  selector: 'app-editable-text',
  template: `
    @if (editing()) {
      <span class="editable editing">
        <input
          #box
          type="text"
          [attr.aria-label]="label()"
          [value]="value() ?? ''"
          [attr.maxlength]="maxLength()"
          (keydown.enter)="save(box.value)"
          (keydown.escape)="cancel()"
        />
        <button type="button" class="small" (click)="save(box.value)">Save</button>
        <button type="button" class="small" (click)="cancel()">Cancel</button>
      </span>
    } @else {
      <span class="editable">
        <span [class.placeholder]="!value()">{{ value() || placeholder() }}</span>
        @if (enabled()) {
          <button type="button" class="link" [attr.aria-label]="'Edit ' + label()" (click)="start()">edit</button>
        }
      </span>
    }
  `,
})
export class EditableTextComponent {
  readonly value = input<string | null>(null);
  readonly label = input.required<string>();
  readonly placeholder = input('none');
  readonly required = input(false);
  readonly enabled = input(true);
  readonly maxLength = input(200);
  readonly saved = output<string | null>();

  protected readonly editing = signal(false);
  private readonly box = viewChild<ElementRef<HTMLInputElement>>('box');

  protected start(): void {
    this.editing.set(true);
    queueMicrotask(() => this.box()?.nativeElement.focus());
  }

  protected save(raw: string): void {
    const next = raw.trim();
    if (!next && this.required()) return;
    this.editing.set(false);
    if ((next || null) !== (this.value() || null)) this.saved.emit(next || null);
  }

  protected cancel(): void {
    this.editing.set(false);
  }
}
