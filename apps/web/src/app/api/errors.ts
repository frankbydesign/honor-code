import { HttpErrorResponse } from '@angular/common/http';

/** One plain sentence for any failed server call. */
export function messageFor(err: unknown): string {
  if (!(err instanceof HttpErrorResponse)) return 'Something went wrong talking to the server';
  const detail = typeof err.error?.detail === 'string' ? (err.error.detail as string) : null;
  switch (err.status) {
    case 401:
      return 'Signed out; sign in again';
    case 404:
      return 'Not found; it may have been removed';
    case 409:
      return detail ?? 'That change conflicts with the current state';
    case 502:
      return 'Extraction failed; see the meeting page for the run';
    case 503:
      return detail ?? 'Not configured yet';
    default:
      return 'Something went wrong talking to the server';
  }
}
