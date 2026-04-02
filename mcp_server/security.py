import os
import time
import json
import logging
import httpx
from jose import jwt, JWTError

logger = logging.getLogger(__name__)


class TokenValidator:
    """Validate JWTs issued by Okta's MCP resource server authorization server."""

    def __init__(self):
        self.issuer: str = os.getenv("OKTA_ISSUER", "")
        self.audience: str = os.getenv("OKTA_MCP_AUDIENCE", "api://mcp-resource-server")
        self._jwks_cache: dict | None = None
        self._jwks_expires_at: float = 0.0

    async def _get_jwks(self) -> dict:
        now = time.time()
        if self._jwks_cache and now < self._jwks_expires_at:
            return self._jwks_cache

        mcp_issuer = os.getenv("OKTA_MCP_RESOURCE_SERVER_ISSUER", self.issuer)
        jwks_uri = f"{mcp_issuer}/v1/keys"
        async with httpx.AsyncClient() as client:
            resp = await client.get(jwks_uri, timeout=10)
            resp.raise_for_status()
            self._jwks_cache = resp.json()
            self._jwks_expires_at = now + 3600
            return self._jwks_cache

    async def validate(self, token: str) -> dict:
        """Validate access token; return claims on success."""
        try:
            header = jwt.get_unverified_header(token)
            kid = header.get("kid")

            jwks = await self._get_jwks()
            pub_key = None
            for k in jwks.get("keys", []):
                if k.get("kid") == kid:
                    pub_key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(k))
                    break

            if pub_key is None:
                raise ValueError(f"No matching key for kid={kid}")

            claims = jwt.decode(
                token,
                pub_key,
                algorithms=["RS256"],
                audience=self.audience,
                issuer=os.getenv("OKTA_MCP_RESOURCE_SERVER_ISSUER", self.issuer),
            )
            logger.info("Token valid for sub=%s", claims.get("sub"))
            return claims
        except (JWTError, ValueError) as exc:
            logger.error("Token validation failed: %s", exc)
            raise
