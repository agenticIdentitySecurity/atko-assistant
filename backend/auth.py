"""
Okta OIDC consumer login via Authorization Code + PKCE.
Uses plain httpx — no extra Okta SDK needed for the web-app OIDC flow.
"""
import base64
import hashlib
import json
import logging
import os
import secrets
import time
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException, Request
from jose import JWTError, jwt

logger = logging.getLogger(__name__)


class OktaAuth:
    def __init__(self, settings):
        self.s = settings
        self._jwks_cache: dict | None = None
        self._jwks_expires_at: float = 0.0

    # ------------------------------------------------------------------
    # PKCE helpers
    # ------------------------------------------------------------------

    def _pkce_pair(self) -> tuple[str, str]:
        verifier = base64.urlsafe_b64encode(os.urandom(40)).decode().rstrip("=")
        digest = hashlib.sha256(verifier.encode()).digest()
        challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
        return verifier, challenge

    # ------------------------------------------------------------------
    # Step 1 — build redirect URL
    # ------------------------------------------------------------------

    def authorization_url(self, request: Request) -> str:
        verifier, challenge = self._pkce_pair()
        state = secrets.token_urlsafe(24)

        # Persist in session for the callback
        request.session["pkce_verifier"] = verifier
        request.session["oauth_state"] = state

        params = {
            "client_id": self.s.OKTA_CLIENT_ID,
            "response_type": "code",
            "response_mode": "form_post",
            "redirect_uri": self.s.OKTA_REDIRECT_URI,
            "scope": "openid profile email",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        return f"{self.s.OKTA_ISSUER}/v1/authorize?{urlencode(params)}"

    # ------------------------------------------------------------------
    # Step 2 — exchange code for tokens
    # ------------------------------------------------------------------

    async def exchange_code(self, code: str, verifier: str) -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.s.OKTA_ISSUER}/v1/token",
                data={
                    "grant_type": "authorization_code",
                    "client_id": self.s.OKTA_CLIENT_ID,
                    "client_secret": self.s.OKTA_CLIENT_SECRET,
                    "code": code,
                    "redirect_uri": self.s.OKTA_REDIRECT_URI,
                    "code_verifier": verifier,
                },
                timeout=15,
            )
        if resp.status_code != 200:
            logger.error("Token exchange failed: %s", resp.text)
            raise HTTPException(status_code=400, detail="Token exchange failed")
        return resp.json()

    # ------------------------------------------------------------------
    # JWT validation
    # ------------------------------------------------------------------

    async def _get_jwks(self) -> dict:
        now = time.time()
        if self._jwks_cache and now < self._jwks_expires_at:
            return self._jwks_cache
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{self.s.OKTA_ISSUER}/v1/keys", timeout=10)
            resp.raise_for_status()
        self._jwks_cache = resp.json()
        self._jwks_expires_at = now + 3600
        return self._jwks_cache

    async def validate_id_token(self, id_token: str) -> dict:
        try:
            header = jwt.get_unverified_header(id_token)
            kid = header.get("kid")

            jwks = await self._get_jwks()
            pub_key = None
            for k in jwks.get("keys", []):
                if k.get("kid") == kid:
                    pub_key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(k))
                    break

            if pub_key is None:
                raise HTTPException(status_code=401, detail="Unknown signing key")

            claims = jwt.decode(
                id_token,
                pub_key,
                algorithms=["RS256"],
                audience=self.s.OKTA_CLIENT_ID,
                issuer=self.s.OKTA_ISSUER,
            )
            return claims
        except JWTError as exc:
            logger.error("ID token validation error: %s", exc)
            raise HTTPException(status_code=401, detail=f"Invalid ID token: {exc}")


# ------------------------------------------------------------------
# FastAPI dependency
# ------------------------------------------------------------------

def require_user(request: Request) -> dict:
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user
