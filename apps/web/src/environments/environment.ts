// The API is reached by relative path on the same origin. In development
// the Angular dev server proxies /api to the FastAPI process (see
// proxy.conf.json); in daily use FastAPI serves the built app itself.
export const environment = {
  production: false,
  apiBaseUrl: '/api',
};
