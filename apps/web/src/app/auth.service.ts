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

  refresh(): void {
    this.http
      .get<MeResponse>(`${environment.apiBaseUrl}/auth/me`, {
        withCredentials: true,
      })
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
    const next = encodeURIComponent(window.location.origin + '/');
    window.location.href = `${environment.apiBaseUrl}/auth/google/login?next=${next}`;
  }

  logout(): void {
    // Clear local state first so the UI transitions immediately; the cookie
    // is cleared by the Set-Cookie header on the server's 303 response
    // regardless of whether the browser successfully follows the redirect.
    this.user.set(null);
    this.http
      .post(`${environment.apiBaseUrl}/auth/logout`, null, {
        withCredentials: true,
      })
      .pipe(catchError(() => of(null)))
      .subscribe();
  }
}
