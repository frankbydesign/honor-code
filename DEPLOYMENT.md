# Deployment

The web frontend (`apps/web`) deploys to Vercel; the API (`apps/api`) deploys
to Railway. Production is served from the `main` branch; staging from the
`develop` branch. Both Vercel deployments hit the same Railway API.

## Topology

| Environment | Frontend (Vercel)                                        | API (Railway)                                          |
| ----------- | -------------------------------------------------------- | ------------------------------------------------------ |
| Production  | `https://honor-code.vercel.app` (set actual URL below)   | `https://honor-code-production.up.railway.app`         |
| Staging     | `https://honor-code-staging.vercel.app` (set actual URL) | same as production                                     |
| Local       | `http://localhost:4200`                                  | `http://localhost:8000` (or override via `environment.ts`) |

> Replace the example Vercel URLs above with the real ones once Vercel
> assigns them. Production/staging Vercel project URLs can be aliased to
> stable domains in the Vercel dashboard.

---

## Vercel setup (one-time)

Project settings:

- **Repository**: `frankbydesign/honor-code`
- **Root directory**: `apps/web`
- **Framework preset**: Angular
- **Build command**: `pnpm build` (or leave default — Vercel auto-detects)
- **Output directory**: `dist/web/browser` (Angular 17+ application builder)
- **Install command**: `pnpm install`
- **Production branch**: `main`
- **Preview branches**: `develop` (everything else stays as default preview)

`apps/web/vercel.json` already pins `framework: angular` and adds a SPA
fallback rewrite, so deep-link refreshes resolve to `index.html`.

### Vercel environment variables

None required at the moment. The API base URL is baked into the build via
`src/environments/environment.prod.ts`. If you ever need to override per
deploy, add a `VERCEL_*`-prefixed variable and read it in a Vercel build
step — but the current setup keeps it simple.

### Stable staging URL

Vercel preview branches get auto-generated URLs that are stable as long
as the branch name is stable. To get a friendly stable URL (e.g.
`honor-code-staging.vercel.app`), assign a custom alias to the `develop`
branch deployment under **Project Settings → Domains**.

---

## Railway setup

The API service is already deployed at
`https://honor-code-production.up.railway.app`. Add or update the
following environment variables on the Railway service:

| Variable             | Required | Notes                                                                                                                                                                                                                         |
| -------------------- | -------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `DATABASE_URL`       | yes      | Railway-managed Postgres reference variable (already set).                                                                                                                                                                    |
| `SESSION_SECRET`     | yes      | Already set. Used to sign the session and OAuth-state cookies.                                                                                                                                                                |
| `ENCRYPTION_KEY`     | yes      | Already set. Fernet key.                                                                                                                                                                                                      |
| `GOOGLE_CLIENT_ID`   | yes      | Already set.                                                                                                                                                                                                                  |
| `GOOGLE_CLIENT_SECRET` | yes    | Already set.                                                                                                                                                                                                                  |
| `ALLOWED_EMAILS`     | yes      | Already set (`frank@centerpointcorp.com`).                                                                                                                                                                                    |
| `OAUTH_REDIRECT_URI` | yes      | Already set to `https://honor-code-production.up.railway.app/auth/google/callback` (recommended on Railway since proxy headers can lie). **Unchanged by this work** — the callback is still backend-handled.                  |
| **`FRONTEND_ORIGINS`** | **new — yes** | Whitespace- or comma-separated list of full origins. **Set to:** `https://<production-vercel-url> https://<staging-vercel-url> http://localhost:4200`. No trailing slashes, no paths. Used for both CORS and `?next=` allowlisting. |

### What `FRONTEND_ORIGINS` controls

1. **CORS allowlist**: only these origins can make credentialed requests
   (e.g. `fetch('/auth/me', { credentials: 'include' })`) to the API.
   Requests from any other origin are blocked by the browser. There are
   no wildcards.
2. **Post-login redirect allowlist**: the value of `?next=` on
   `/auth/google/login` must have an origin that exactly matches one
   entry in `FRONTEND_ORIGINS`, otherwise login returns 400. This stops
   the API from being abused as an open redirect.

---

## Google Cloud Console

**No changes required.** The OAuth callback is handled by the API
(`/auth/google/callback` on Railway), not the frontend, so the
authorized redirect URI registered with Google
(`https://honor-code-production.up.railway.app/auth/google/callback`)
stays as-is. The frontend only initiates login by navigating the
browser to `${apiBaseUrl}/auth/google/login?next=<frontend_url>`.

If you ever switch to a frontend-handled callback you'd need to register
the Vercel URLs there instead — but that's out of scope for this task.

---

## How the cross-origin auth works

1. User clicks "Sign in with Google" on `https://<vercel-url>/`.
2. Browser navigates (top-level) to
   `https://<api>/auth/google/login?next=https%3A%2F%2F<vercel-url>%2F`.
3. API validates `next` against `FRONTEND_ORIGINS`, stashes it in the
   signed `honor_code_oauth` cookie (Authlib's session), and redirects
   the browser to Google.
4. Google bounces the browser back to
   `https://<api>/auth/google/callback?code=...`.
5. API exchanges the code, creates a `users` row (if needed) + a
   `sessions` row, sets `honor_code_session` as a `SameSite=None; Secure;
   HttpOnly` cookie, and 303-redirects back to the validated `next`
   URL.
6. The Angular app loads, calls
   `fetch('${apiBaseUrl}/auth/me', { credentials: 'include' })`, and
   shows the signed-in email.

The session cookie is `SameSite=None; Secure` because cross-site fetches
from `*.vercel.app` to `*.railway.app` won't include `SameSite=Lax`
cookies. The OAuth-state cookie stays `SameSite=Lax` because it's only
read on top-level navigation back from Google.

---

## Local development

```bash
# Backend
cd apps/api
DATABASE_URL='...' SESSION_SECRET='...' ENCRYPTION_KEY='...' \
  GOOGLE_CLIENT_ID='...' GOOGLE_CLIENT_SECRET='...' \
  ALLOWED_EMAILS='you@example.com' \
  FRONTEND_ORIGINS='http://localhost:4200' \
  uv run uvicorn app.main:app --reload

# Frontend (separate terminal)
cd apps/web
pnpm start
```

Local OAuth needs `http://localhost:8000/auth/google/callback` registered
in Google Cloud Console as an authorized redirect URI. (This is the
preexisting local-dev setup — unchanged by this work.)

To point local `ng serve` at the deployed Railway API instead of a local
backend, edit `apps/web/src/environments/environment.ts` (do not commit
the change). The production build always uses
`environment.prod.ts` via `angular.json`'s `fileReplacements`.

---

## Verifying the deploy

After Vercel finishes the production deploy and you've set
`FRONTEND_ORIGINS` on Railway:

```bash
# 1. CORS preflight allows the production origin
curl -i -X OPTIONS https://honor-code-production.up.railway.app/auth/me \
  -H "Origin: https://<production-vercel-url>" \
  -H "Access-Control-Request-Method: GET"
# Expect: 200 + access-control-allow-origin: https://<production-vercel-url>

# 2. CORS preflight blocks a non-allowlisted origin
curl -i -X OPTIONS https://honor-code-production.up.railway.app/auth/me \
  -H "Origin: http://localhost:9999" \
  -H "Access-Control-Request-Method: GET"
# Expect: no access-control-allow-origin header in the response

# 3. /auth/google/login rejects an unlisted next URL
curl -i "https://honor-code-production.up.railway.app/auth/google/login?next=https://evil.com/"
# Expect: 400, body {"detail":"next url not in allowlist"}
```

End-to-end check (in a browser): visit each Vercel URL, click "Sign in
with Google", complete the consent screen, and confirm you land back on
the same Vercel URL with "Signed in as <email>" rendered.
