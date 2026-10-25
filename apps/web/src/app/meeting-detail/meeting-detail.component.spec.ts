import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { MeetingDetailComponent } from './meeting-detail.component';
import { makeCommitment, makeDocumentDetail } from '../testing';

describe('MeetingDetailComponent', () => {
  let http: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [MeetingDetailComponent],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    }).compileComponents();
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  async function render() {
    const fixture = TestBed.createComponent(MeetingDetailComponent);
    fixture.componentRef.setInput('id', 'doc-1');
    fixture.detectChanges();
    http.expectOne('/api/documents/doc-1').flush(makeDocumentDetail());
    await fixture.whenStable();
    fixture.detectChanges();
    return fixture;
  }

  const button = (el: HTMLElement, label: string) =>
    Array.from(el.querySelectorAll<HTMLButtonElement>('button')).find((b) => b.textContent!.trim() === label);

  it('shows the meeting, its runs, its commitments, and a link to Fathom', async () => {
    const fixture = await render();
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('h2')?.textContent).toContain('Budget check-in');
    expect(el.querySelector<HTMLAnchorElement>('a[href="https://fathom.video/share/invented"]')).not.toBeNull();
    expect(el.textContent).toContain('succeeded');
    expect(el.querySelectorAll('[data-testid="commitment-card"]').length).toBe(1);
  });

  it('Re-extract asks for confirmation before calling the server', async () => {
    const fixture = await render();
    const el = fixture.nativeElement as HTMLElement;

    button(el, 'Re-extract')!.click();
    fixture.detectChanges();
    http.expectNone('/api/documents/doc-1/extract');

    button(el, 'Yes, re-extract')!.click();
    const req = http.expectOne('/api/documents/doc-1/extract');
    expect(req.request.method).toBe('POST');
    req.flush({ run: makeDocumentDetail().runs[0], commitments: [makeCommitment({ id: 'c-9' })] });
    http.expectOne('/api/documents/doc-1').flush(makeDocumentDetail());
  });

  it('a failed re-extract explains where to look', async () => {
    const fixture = await render();
    const el = fixture.nativeElement as HTMLElement;
    button(el, 'Re-extract')!.click();
    fixture.detectChanges();
    button(el, 'Yes, re-extract')!.click();
    http
      .expectOne('/api/documents/doc-1/extract')
      .flush({ detail: 'extraction failed (RuntimeError)', run_id: 'run-2' }, { status: 502, statusText: 'Bad Gateway' });
    http.expectOne('/api/documents/doc-1').flush(makeDocumentDetail());
    fixture.detectChanges();
    expect(el.querySelector('[role="alert"]')?.textContent).toContain('Extraction failed; see the meeting page for the run');
  });

  it('Remove asks for confirmation, then deletes and goes back to Meetings', async () => {
    const fixture = await render();
    const el = fixture.nativeElement as HTMLElement;
    const router = TestBed.inject(Router);
    const navigate = vi.spyOn(router, 'navigateByUrl').mockResolvedValue(true);

    button(el, 'Remove')!.click();
    fixture.detectChanges();
    http.expectNone({ method: 'DELETE', url: '/api/documents/doc-1' });
    expect(navigate).not.toHaveBeenCalled();

    button(el, 'Yes, remove')!.click();
    http.expectOne({ method: 'DELETE', url: '/api/documents/doc-1' }).flush(null, { status: 204, statusText: 'No Content' });
    await fixture.whenStable();
    expect(navigate).toHaveBeenCalledWith('/meetings');
  });

  it('Cancel backs out of a confirmation', async () => {
    const fixture = await render();
    const el = fixture.nativeElement as HTMLElement;
    button(el, 'Remove')!.click();
    fixture.detectChanges();
    button(el, 'Cancel')!.click();
    fixture.detectChanges();
    expect(button(el, 'Yes, remove')).toBeUndefined();
  });

  it('a missing meeting shows a message', async () => {
    const fixture = TestBed.createComponent(MeetingDetailComponent);
    fixture.componentRef.setInput('id', 'gone');
    fixture.detectChanges();
    http.expectOne('/api/documents/gone').flush({ detail: 'not found' }, { status: 404, statusText: 'Not Found' });
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).querySelector('[role="alert"]')).not.toBeNull();
  });
});
