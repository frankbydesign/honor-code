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

  readonly currentUser = this.user.asReadonly();
  readonly isAuthenticated = computed(() => this.user() !== null);
  readonly hasChecked = this.checked.asReadonly();

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
    const next = encodeURIComponent(window.location.origin + '/');
    window.location.href = `${environment.apiBaseUrl}/auth/google/login?next=${next}`;
  }
}
