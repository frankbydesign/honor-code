import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { AuthService } from './auth.service';
import { authExpiredInterceptor } from './auth-expired.interceptor';

describe('authExpiredInterceptor', () => {
  let http: HttpTestingController;
  let client: HttpClient;
  let refresh: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    refresh = vi.fn();
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([authExpiredInterceptor])),
        provideHttpClientTesting(),
        { provide: AuthService, useValue: { refresh } },
      ],
    });
    http = TestBed.inject(HttpTestingController);
    client = TestBed.inject(HttpClient);
  });

  afterEach(() => http.verify());

  it('a 401 from the API re-checks the session, so the sign-in screen can appear', () => {
    client.get('/api/commitments').subscribe({ error: () => undefined });
    http.expectOne('/api/commitments').flush({ detail: 'not authenticated' }, { status: 401, statusText: 'Unauthorized' });
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it('the session check itself never triggers another check', () => {
    client.get('/api/auth/me').subscribe({ error: () => undefined });
    http.expectOne('/api/auth/me').flush({}, { status: 401, statusText: 'Unauthorized' });
    expect(refresh).not.toHaveBeenCalled();
  });

  it('other errors pass through untouched', () => {
    let status = 0;
    client.get('/api/commitments').subscribe({ error: (e) => (status = e.status) });
    http.expectOne('/api/commitments').flush({}, { status: 500, statusText: 'Server Error' });
    expect(status).toBe(500);
    expect(refresh).not.toHaveBeenCalled();
  });
});
