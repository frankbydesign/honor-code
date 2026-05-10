"""Authlib OAuth client for Google.

We let Authlib handle the OIDC discovery, state parameter, and
PKCE/nonce. State is stashed in Starlette's signed session cookie
(see SessionMiddleware in main) and round-tripped through Google.
"""

from __future__ import annotations

from authlib.integrations.starlette_client import OAuth

from app.auth import config

oauth = OAuth()
oauth.register(
    name="google",
    client_id=config.GOOGLE_CLIENT_ID,
    client_secret=config.GOOGLE_CLIENT_SECRET,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)
