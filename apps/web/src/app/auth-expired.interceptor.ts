import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { catchError, throwError } from 'rxjs';
import { environment } from '../environments/environment';
import { AuthService } from './auth.service';

/**
 * When any API call comes back 401 the session has ended (expired, or
 * signed out elsewhere). Re-check it, so the app switches to the sign-in
 * screen instead of showing "Signed out" next to a Sign out button.
 */
export const authExpiredInterceptor: HttpInterceptorFn = (req, next) => {
  const auth = inject(AuthService);
  return next(req).pipe(
    catchError((err: unknown) => {
      if (
        err instanceof HttpErrorResponse &&
        err.status === 401 &&
        !req.url.startsWith(`${environment.apiBaseUrl}/auth/`)
      ) {
        auth.refresh();
      }
      return throwError(() => err);
    }),
  );
};
