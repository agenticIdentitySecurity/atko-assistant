"""
On-behalf-of token exchange using Okta's Cross-App Access flow.

Uses the okta-client-python SDK:
  https://github.com/okta/okta-client-python

Flow:
  1. Web app holds the logged-in user's ID token (from OIDC login).
  2. Service app (with RS256 private key) does a two-step exchange:
       a. flow.start(token=id_token)  → ID-JAG assertion
       b. flow.resume()               → access token for MCP resource server
  3. That access token is passed to the MCP server subprocess as MCP_ACCESS_TOKEN.
"""
import logging
from datetime import datetime, timedelta

from fastapi import HTTPException
from jose import jwt as jose_jwt

from okta_client.authfoundation import (
    ClientAssertionAuthorization,
    LocalKeyProvider,
    OAuth2Client,
    OAuth2ClientConfiguration,
)
from okta_client.authfoundation.oauth2.jwt_bearer_claims import JWTBearerClaims
from okta_client.oauth2auth import CrossAppAccessFlow, CrossAppAccessTarget

logger = logging.getLogger(__name__)


class TokenExchanger:
    def __init__(self, settings):
        self.s = settings
        self._client: OAuth2Client | None = None
        # Per-user token cache: sub -> {"token": str, "expires_at": datetime}
        self._cache: dict[str, dict] = {}

    def _build_client(self) -> OAuth2Client:
        key_provider = LocalKeyProvider.from_pem_file(
            self.s.OKTA_SERVICE_KEY_PATH, algorithm="RS256"
        )
        token_endpoint = f"{self.s.OKTA_ISSUER}/v1/token"
        config = OAuth2ClientConfiguration(
            issuer=self.s.OKTA_ISSUER,
            client_authorization=ClientAssertionAuthorization(
                assertion_claims=JWTBearerClaims(
                    issuer=self.s.OKTA_SERVICE_CLIENT_ID,
                    subject=self.s.OKTA_SERVICE_CLIENT_ID,
                    audience=token_endpoint,
                    expires_in=300,
                ),
                key_provider=key_provider,
            ),
        )
        return OAuth2Client(configuration=config)

    @property
    def client(self) -> OAuth2Client:
        if self._client is None:
            self._client = self._build_client()
        return self._client

    async def exchange(self, id_token: str) -> str:
        """Exchange user ID token for an MCP-resource-server access token."""
        # Determine cache key from unverified sub claim
        try:
            unverified = jose_jwt.get_unverified_claims(id_token)
            sub = unverified["sub"]
        except Exception:
            sub = id_token[:32]  # fallback

        # Return cached token if still valid
        cached = self._cache.get(sub)
        if cached and cached["expires_at"] > datetime.utcnow():
            logger.info("Using cached MCP token for sub=%s", sub)
            return cached["token"]

        logger.info("Performing CrossAppAccessFlow for sub=%s", sub)
        try:
            target = CrossAppAccessTarget(
                issuer=self.s.OKTA_MCP_RESOURCE_SERVER_ISSUER,
            )
            flow = CrossAppAccessFlow(client=self.client, target=target)
            await flow.start(token=id_token)
            result = await flow.resume()

            # result may be a token object or a string depending on SDK version
            token_str: str = (
                result.access_token if hasattr(result, "access_token") else str(result)
            )

            self._cache[sub] = {
                "token": token_str,
                "expires_at": datetime.utcnow() + timedelta(hours=1),
            }
            logger.info("Token exchange succeeded for sub=%s", sub)
            return token_str
        except Exception as exc:
            logger.error("CrossAppAccessFlow failed: %s", exc)
            raise HTTPException(
                status_code=502, detail=f"Token exchange failed: {exc}"
            ) from exc
