import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { SyncService } from './sync.service';
import { makeSyncStatus } from './testing';

describe('SyncService', () => {
  let svc: SyncService;
  let http: HttpTestingController;

  beforeEach(() => {
    vi.useFakeTimers();
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
    svc = TestBed.inject(SyncService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
    vi.useRealTimers();
  });

  it('refresh() loads the status', () => {
    svc.refresh();
    http.expectOne('/api/sync').flush(makeSyncStatus({ configured: false, missing: ['FATHOM_API_KEY'] }));
    expect(svc.status()?.missing).toEqual(['FATHOM_API_KEY']);
  });

  it('syncNow() posts, then polls every two seconds while running, then stops', () => {
    svc.syncNow();
    const post = http.expectOne('/api/sync');
    expect(post.request.method).toBe('POST');
    expect(post.request.withCredentials).toBe(true);
    post.flush({ run: { id: 'r1', status: 'running' } }, { status: 202, statusText: 'Accepted' });

    http.expectOne({ method: 'GET', url: '/api/sync' }).flush(makeSyncStatus({ running: true }));
    expect(svc.syncing()).toBe(true);

    vi.advanceTimersByTime(2000);
    http.expectOne({ method: 'GET', url: '/api/sync' }).flush(makeSyncStatus({ running: true }));

    vi.advanceTimersByTime(2000);
    http.expectOne({ method: 'GET', url: '/api/sync' }).flush(makeSyncStatus({ running: false }));
    expect(svc.syncing()).toBe(false);

    vi.advanceTimersByTime(10000);
    http.expectNone('/api/sync');
  });

  it('emits a finished signal when a sync ends, so screens can reload', () => {
    const before = svc.finishedCount();
    svc.syncNow();
    http.expectOne({ method: 'POST', url: '/api/sync' }).flush({ run: { id: 'r1' } }, { status: 202, statusText: 'Accepted' });
    http.expectOne({ method: 'GET', url: '/api/sync' }).flush(makeSyncStatus({ running: false }));
    expect(svc.finishedCount()).toBe(before + 1);
  });

  it('a 409 says a sync is already running and keeps polling', () => {
    svc.syncNow();
    http.expectOne({ method: 'POST', url: '/api/sync' }).flush({ detail: 'a sync is already running' }, { status: 409, statusText: 'Conflict' });
    expect(svc.error()).toBe('A sync is already running');
    http.expectOne({ method: 'GET', url: '/api/sync' }).flush(makeSyncStatus({ running: false }));
  });

  it('a 503 shows what is missing from the configuration', () => {
    svc.syncNow();
    http
      .expectOne({ method: 'POST', url: '/api/sync' })
      .flush(
        { detail: 'sync is not configured: set FATHOM_API_KEY, ANTHROPIC_API_KEY in apps/api/.env' },
        { status: 503, statusText: 'Service Unavailable' },
      );
    expect(svc.error()).toContain('FATHOM_API_KEY');
    expect(svc.error()).toContain('ANTHROPIC_API_KEY');
    expect(svc.syncing()).toBe(false);
  });

  it('a failed check during a sync retries instead of freezing on "Syncing"', () => {
    svc.syncNow();
    http.expectOne({ method: 'POST', url: '/api/sync' }).flush({ run: { id: 'r1' } }, { status: 202, statusText: 'Accepted' });
    http.expectOne({ method: 'GET', url: '/api/sync' }).flush(makeSyncStatus({ running: true }));

    vi.advanceTimersByTime(2000);
    http.expectOne({ method: 'GET', url: '/api/sync' }).flush({}, { status: 0, statusText: 'Unknown Error' });
    expect(svc.syncing()).toBe(true);

    vi.advanceTimersByTime(5000);
    http.expectOne({ method: 'GET', url: '/api/sync' }).flush(makeSyncStatus({ running: false }));
    expect(svc.syncing()).toBe(false);
    expect(svc.finishedCount()).toBe(1);
  });

  it('notices a sync the app ran on its own schedule', () => {
    const lastRun = (id: string) =>
      makeSyncStatus({ last_run: { id, status: 'succeeded' } as never });
    svc.refresh();
    http.expectOne('/api/sync').flush(lastRun('r1'));
    expect(svc.finishedCount()).toBe(0);

    vi.advanceTimersByTime(60000);
    http.expectOne('/api/sync').flush(lastRun('r1'));
    expect(svc.finishedCount()).toBe(0);

    vi.advanceTimersByTime(60000);
    http.expectOne('/api/sync').flush(lastRun('r2'));
    expect(svc.finishedCount()).toBe(1);
  });
});
