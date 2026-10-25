import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { ReviewComponent } from './review.component';
import { makeCommitment } from '../testing';

describe('ReviewComponent', () => {
  let http: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ReviewComponent],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    }).compileComponents();
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  async function render(items: ReturnType<typeof makeCommitment>[]) {
    const fixture = TestBed.createComponent(ReviewComponent);
    fixture.detectChanges();
    http.expectOne('/api/commitments').flush(items);
    await fixture.whenStable();
    fixture.detectChanges();
    return fixture;
  }

  const cards = (el: HTMLElement) => Array.from(el.querySelectorAll('[data-testid="commitment-card"]'));
  const buttons = (card: Element) =>
    Array.from(card.querySelectorAll('[data-testid="card-actions"] button')).map((b) => b.textContent!.trim());
  const tab = (el: HTMLElement, name: string) =>
    Array.from(el.querySelectorAll<HTMLButtonElement>('[role="tab"]')).find((t) => t.textContent!.includes(name))!;

  it('shows one card per candidate, grouped by person, with Accept and Reject', async () => {
    const fixture = await render([
      makeCommitment({ id: '1', counterparty: 'Sam' }),
      makeCommitment({ id: '2', counterparty: 'Alice Kim' }),
      makeCommitment({ id: '3', status: 'accepted' }),
    ]);
    const el = fixture.nativeElement as HTMLElement;
    expect(cards(el).length).toBe(2);
    const headings = Array.from(el.querySelectorAll('[data-testid="group-label"]')).map((h) => h.textContent!.trim());
    expect(headings).toEqual(['Alice Kim', 'Sam']);
    expect(buttons(cards(el)[0])).toEqual(['Accept', 'Reject']);
  });

  it('each tab shows the right actions', async () => {
    const fixture = await render([
      makeCommitment({ id: '1', status: 'accepted' }),
      makeCommitment({ id: '2', status: 'done' }),
      makeCommitment({ id: '3', status: 'dropped' }),
    ]);
    const el = fixture.nativeElement as HTMLElement;

    tab(el, 'Accepted').click();
    fixture.detectChanges();
    expect(buttons(cards(el)[0])).toEqual(['Done', 'Drop']);

    tab(el, 'Done').click();
    fixture.detectChanges();
    expect(buttons(cards(el)[0])).toEqual(['Reopen']);

    tab(el, 'Rejected').click();
    fixture.detectChanges();
    expect(buttons(cards(el)[0])).toEqual(['Restore']);
  });

  it('Accept disables the card buttons while the request is in flight', async () => {
    const fixture = await render([makeCommitment()]);
    const el = fixture.nativeElement as HTMLElement;
    const accept = Array.from(cards(el)[0].querySelectorAll('button')).find((b) => b.textContent!.trim() === 'Accept')!;

    accept.click();
    fixture.detectChanges();
    expect(accept.disabled).toBe(true);

    http.expectOne('/api/commitments/c-1/status').flush(makeCommitment({ status: 'accepted' }));
    fixture.detectChanges();
    expect(cards(el).length).toBe(0); // moved to the Accepted tab
  });

  it('renders model text as text, never as HTML', async () => {
    const fixture = await render([makeCommitment({ summary: '<script>alert(1)</script>', quote: '<b>bold</b>' })]);
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('script')).toBeNull();
    expect(el.querySelector('[data-testid="commitment-card"] b')).toBeNull();
    expect(el.textContent).toContain('<script>alert(1)</script>');
  });

  it('marks a quote that was not found in the transcript', async () => {
    const fixture = await render([makeCommitment({ quote_found: false })]);
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('not found verbatim');
  });

  it('shows a message when the list cannot load', async () => {
    const fixture = TestBed.createComponent(ReviewComponent);
    fixture.detectChanges();
    http.expectOne('/api/commitments').flush({ detail: 'x' }, { status: 500, statusText: 'Server Error' });
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).querySelector('[role="alert"]')?.textContent).toContain(
      'Something went wrong talking to the server',
    );
  });

  it('shows a per-card message when a move is refused', async () => {
    const fixture = await render([makeCommitment()]);
    const el = fixture.nativeElement as HTMLElement;
    Array.from(cards(el)[0].querySelectorAll('button')).find((b) => b.textContent!.trim() === 'Reject')!.click();
    http
      .expectOne('/api/commitments/c-1/status')
      .flush({ detail: 'cannot move a commitment from candidate to rejected' }, { status: 409, statusText: 'Conflict' });
    fixture.detectChanges();
    expect(cards(el)[0].textContent).toContain('cannot move a commitment from candidate to rejected');
  });

  it('an empty candidates tab says so', async () => {
    const fixture = await render([]);
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('Nothing to review');
  });
});
