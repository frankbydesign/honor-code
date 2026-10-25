import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { CommitmentsService } from './commitments.service';
import { makeCommitment } from './testing';

describe('CommitmentsService', () => {
  let svc: CommitmentsService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
    svc = TestBed.inject(CommitmentsService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('load() fetches every commitment with credentials', () => {
    svc.load();
    const req = http.expectOne('/api/commitments');
    expect(req.request.method).toBe('GET');
    expect(req.request.withCredentials).toBe(true);
    req.flush([makeCommitment(), makeCommitment({ id: 'c-2' })]);
    expect(svc.items().length).toBe(2);
    expect(svc.loaded()).toBe(true);
    expect(svc.error()).toBeNull();
  });

  it('a failed load shows a message and keeps what was already shown', () => {
    svc.load();
    http.expectOne('/api/commitments').flush([makeCommitment()]);
    svc.load();
    http.expectOne('/api/commitments').flush({ detail: 'boom' }, { status: 500, statusText: 'Server Error' });
    expect(svc.error()).toBe('Something went wrong talking to the server');
    expect(svc.items().length).toBe(1);
  });

  it('a 401 says you are signed out', () => {
    svc.load();
    http.expectOne('/api/commitments').flush({ detail: 'not authenticated' }, { status: 401, statusText: 'Unauthorized' });
    expect(svc.error()).toBe('Signed out; sign in again');
  });

  it('transition() posts the move and replaces only that item', () => {
    svc.load();
    http.expectOne('/api/commitments').flush([makeCommitment(), makeCommitment({ id: 'c-2', summary: 'Other' })]);

    svc.transition('c-1', 'accepted');
    expect(svc.isPending('c-1')).toBe(true);
    const req = http.expectOne('/api/commitments/c-1/status');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ to: 'accepted' });
    req.flush(makeCommitment({ status: 'accepted' }));

    expect(svc.isPending('c-1')).toBe(false);
    expect(svc.items().map((c) => [c.id, c.status])).toEqual([
      ['c-1', 'accepted'],
      ['c-2', 'candidate'],
    ]);
  });

  it('transition() sends a note when given one', () => {
    svc.transition('c-1', 'dropped', 'No longer needed');
    const req = http.expectOne('/api/commitments/c-1/status');
    expect(req.request.body).toEqual({ to: 'dropped', note: 'No longer needed' });
    req.flush(makeCommitment({ status: 'dropped' }));
  });

  it('a 409 on a move shows the server reason on that item and changes nothing', () => {
    svc.load();
    http.expectOne('/api/commitments').flush([makeCommitment()]);
    svc.transition('c-1', 'done');
    http
      .expectOne('/api/commitments/c-1/status')
      .flush({ detail: 'cannot move a commitment from candidate to done' }, { status: 409, statusText: 'Conflict' });

    expect(svc.itemError('c-1')).toBe('cannot move a commitment from candidate to done');
    expect(svc.items()[0].status).toBe('candidate');
    expect(svc.error()).toBeNull();
  });

  it('edit() patches only the given fields and replaces the item', () => {
    svc.load();
    http.expectOne('/api/commitments').flush([makeCommitment()]);
    svc.edit('c-1', { summary: 'Send the Q4 budget' });
    const req = http.expectOne('/api/commitments/c-1');
    expect(req.request.method).toBe('PATCH');
    expect(req.request.body).toEqual({ summary: 'Send the Q4 budget' });
    req.flush(makeCommitment({ summary: 'Send the Q4 budget' }));
    expect(svc.items()[0].summary).toBe('Send the Q4 budget');
  });

  it('grouped() groups by counterparty with no-one-in-particular last', () => {
    const groups = CommitmentsService.group([
      makeCommitment({ id: 'a', counterparty: null }),
      makeCommitment({ id: 'b', counterparty: 'Sam' }),
      makeCommitment({ id: 'c', counterparty: 'Alice Kim' }),
      makeCommitment({ id: 'd', counterparty: 'Sam' }),
    ]);
    expect(groups.map((g) => g.label)).toEqual(['Alice Kim', 'Sam', 'No one in particular']);
    expect(groups[1].items.map((c) => c.id)).toEqual(['b', 'd']);
  });

  it('tab filters split the list by status', () => {
    svc.load();
    http.expectOne('/api/commitments').flush([
      makeCommitment({ id: '1', status: 'candidate' }),
      makeCommitment({ id: '2', status: 'accepted' }),
      makeCommitment({ id: '3', status: 'done' }),
      makeCommitment({ id: '4', status: 'rejected' }),
      makeCommitment({ id: '5', status: 'dropped' }),
    ]);
    expect(svc.forTab('candidates').map((c) => c.id)).toEqual(['1']);
    expect(svc.forTab('accepted').map((c) => c.id)).toEqual(['2']);
    expect(svc.forTab('done').map((c) => c.id)).toEqual(['3']);
    expect(svc.forTab('closed').map((c) => c.id)).toEqual(['4', '5']);
  });

  it('a refused edit (422) says the value was not accepted', () => {
    svc.edit('c-1', { summary: 'x'.repeat(600) });
    http
      .expectOne('/api/commitments/c-1')
      .flush({ detail: [{ msg: 'too long' }] }, { status: 422, statusText: 'Unprocessable Entity' });
    expect(svc.itemError('c-1')).toBe('That value was not accepted; check that it is not empty or too long');
  });
});
