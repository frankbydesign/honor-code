import { HttpClient } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { catchError, of, tap } from 'rxjs';
import { environment } from '../environments/environment';

interface MeResponse {
  email: string;
  display_name: string | null;
}

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly http = inject(HttpClient);
  private readonly user = signal<MeResponse | null>(null);
  private readonly checked = signal(false);
  private readonly loggingIn = signal(false);

  readonly currentUser = this.user.asReadonly();
  readonly isAuthenticated = computed(() => this.user() !== null);
  readonly hasChecked = this.checked.asReadonly();
  readonly loginInProgress = this.loggingIn.asReadonly();

  readonly loginUrl = `${environment.apiBaseUrl}/auth/google/login`;

  refresh(): void {
    this.http
      .get<MeResponse>(`${environment.apiBaseUrl}/auth/me`, { withCredentials: true })
      .pipe(
        tap((u) => this.user.set(u)),
        catchError(() => {
          this.user.set(null);
          return of(null);
        }),
      )
      .subscribe(() => this.checked.set(true));
  }

  login(): void {
    if (this.loggingIn()) return;
    this.loggingIn.set(true);
    // Top-level navigation: the API redirects to Google and, after the
    // callback, back to POST_LOGIN_REDIRECT (this origin by default).
    this.navigate(this.loginUrl);
  }

  logout(): void {
    // The server answers 204 and clears the cookie. Re-check with the
    // server afterwards rather than assuming, so the UI reflects reality
    // even if the request failed.
    this.http
      .post(`${environment.apiBaseUrl}/auth/logout`, null, { withCredentials: true })
      .pipe(catchError(() => of(null)))
      .subscribe(() => this.refresh());
  }

  /** Seam for tests; a real navigation would unload the test page. */
  protected navigate(url: string): void {
    window.location.href = url;
  }
}
