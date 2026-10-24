import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Injectable } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { AuthService } from './auth.service';

@Injectable()
class RecordingAuthService extends AuthService {
  readonly navigated: string[] = [];
  protected override navigate(url: string): void {
    this.navigated.push(url);
  }
}

describe('AuthService', () => {
  let auth: RecordingAuthService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: AuthService, useClass: RecordingAuthService },
      ],
    });
    auth = TestBed.inject(AuthService) as RecordingAuthService;
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('refresh() calls GET /api/auth/me and sets the user on 200', () => {
    auth.refresh();
    const req = http.expectOne('/api/auth/me');
    expect(req.request.method).toBe('GET');
    expect(req.request.withCredentials).toBe(true);
    req.flush({ email: 'frank@example.com', display_name: 'Frank' });

    expect(auth.currentUser()?.email).toBe('frank@example.com');
    expect(auth.isAuthenticated()).toBe(true);
    expect(auth.hasChecked()).toBe(true);
  });

  it('refresh() sets user null and hasChecked true on 401', () => {
    auth.refresh();
    http.expectOne('/api/auth/me').flush({ detail: 'not authenticated' }, { status: 401, statusText: 'Unauthorized' });

    expect(auth.currentUser()).toBeNull();
    expect(auth.isAuthenticated()).toBe(false);
    expect(auth.hasChecked()).toBe(true);
  });

  it('logout() posts to /api/auth/logout, then re-checks /api/auth/me', () => {
    auth.logout();
    const post = http.expectOne('/api/auth/logout');
    expect(post.request.method).toBe('POST');
    expect(post.request.withCredentials).toBe(true);
    post.flush(null, { status: 204, statusText: 'No Content' });

    http.expectOne('/api/auth/me').flush({ detail: 'not authenticated' }, { status: 401, statusText: 'Unauthorized' });
    expect(auth.isAuthenticated()).toBe(false);
  });

  it('login() navigates to exactly /api/auth/google/login, once', () => {
    auth.login();
    auth.login();
    expect(auth.navigated).toEqual(['/api/auth/google/login']);
    expect(auth.loginInProgress()).toBe(true);
  });
});
