"""
Cross-App Access token exchange using okta-client-python SDK.

Two-step XAA flow (matches Okta sequence diagram):
  1. start()  — AI Agent exchanges user's id_token for an ID-JAG at the Org AS
  2. resume() — AI Agent exchanges ID-JAG for an access_token at the Custom AS
"""
import logging
from datetime import datetime, timedelta

import httpx
from fastapi import HTTPException
from jose import jwt as jose_jwt

from okta_client.authfoundation import (
    ClientAssertionAuthorization,
    JWTBearerClaims,
    LocalKeyProvider,
    OAuth2Client,
    OAuth2ClientConfiguration,
)
from okta_client.oauth2auth import (
    CrossAppAccessFlow,
    CrossAppAccessTarget,
)

logger = logging.getLogger(__name__)


class TokenExchanger:
    def __init__(self, settings):
        self.s = settings
        self._cache: dict[str, dict] = {}
        self._key_provider: LocalKeyProvider | None = None
        self._org_token_endpoint: str | None = None

    def _get_key_provider(self) -> LocalKeyProvider:
        if self._key_provider is None:
            self._key_provider = LocalKeyProvider.from_pem_file(
                self.s.OKTA_SERVICE_KEY_PATH,
                algorithm="RS256",
                key_id=self.s.OKTA_SERVICE_KEY_ID,
            )
        return self._key_provider

    async def _get_org_token_endpoint(self) -> str:
        """Discover and cache the Org AS token endpoint from .well-known metadata."""
        if self._org_token_endpoint is None:
            url = f"{self.s.OKTA_ORG_URL}/.well-known/oauth-authorization-server"
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, timeout=10)
                resp.raise_for_status()
            self._org_token_endpoint = resp.json()["token_endpoint"]
            logger.info("Org AS token endpoint: %s", self._org_token_endpoint)
        return self._org_token_endpoint

    def _build_agent_client(self, audience: str) -> OAuth2Client:
        """Build an OAuth2Client for the AI Agent at the Org AS.

        The audience must be the Org AS token endpoint — Okta requires
        the client_assertion JWT's aud to match the endpoint being called.
        """
        key_provider = self._get_key_provider()
        claims = JWTBearerClaims(
            issuer=self.s.OKTA_SERVICE_CLIENT_ID,
            subject=self.s.OKTA_SERVICE_CLIENT_ID,
            audience=audience,
            expires_in=300,
        )
        client_auth = ClientAssertionAuthorization(
            assertion_claims=claims,
            key_provider=key_provider,
        )
        config = OAuth2ClientConfiguration(
            issuer=self.s.OKTA_ORG_URL,
            client_authorization=client_auth,
        )
        return OAuth2Client(configuration=config)

    @staticmethod
    def _extract_claims(jwt_str: str) -> dict | None:
        """Decode a JWT and return all claims."""
        try:
            return jose_jwt.get_unverified_claims(jwt_str)
        except Exception:
            return None

    async def exchange(self, id_token: str, oidc_access_token: str = "") -> dict:
        """Exchange user's id_token → ID-JAG → access_token via XAA.

        Returns dict with access_token string and decoded claims from each step.
        """
        try:
            sub = jose_jwt.get_unverified_claims(id_token).get("sub", id_token[:32])
        except Exception:
            sub = id_token[:32]

        cached = self._cache.get(sub)
        if cached and cached["expires_at"] > datetime.utcnow():
            logger.info("Using cached MCP token for sub=%s", sub)
            return dict(cached["result"])

        logger.info("CrossAppAccessFlow for sub=%s", sub)

        try:
            # Discover the Org AS token endpoint (cached after first call).
            # The JWT assertion's aud claim MUST match this endpoint.
            org_token_endpoint = await self._get_org_token_endpoint()

            # Build AI Agent client with correct audience for Org AS
            agent_client = self._build_agent_client(audience=org_token_endpoint)

            # Target = Custom AS (Managed Connection) for MCP resource server
            target = CrossAppAccessTarget(
                issuer=self.s.OKTA_MCP_RESOURCE_SERVER_ISSUER,
            )
            flow = CrossAppAccessFlow(client=agent_client, target=target)

            # Step 1: Exchange id_token for ID-JAG at Org AS
            logger.info("XAA step 1: id_token → ID-JAG at Org AS")
            await flow.start(
                token=id_token,
                token_type="id_token",
                scope=["frontier:read"],
            )

            # Extract ID-JAG claims from the flow context
            id_jag_claims = None
            ctx = flow._context
            if ctx and ctx.id_jag_token:
                id_jag_claims = self._extract_claims(ctx.id_jag_token.access_token)

            # Step 2: Exchange ID-JAG for access_token at Custom AS
            logger.info("XAA step 2: ID-JAG → access_token at Custom AS")
            token = await flow.resume()

            access_token = token.access_token
            access_token_claims = self._extract_claims(access_token)
            logger.info("CrossAppAccessFlow succeeded for sub=%s", sub)

            result = {
                "access_token": access_token,
                "id_jag_claims": id_jag_claims,
                "access_token_claims": access_token_claims,
            }
            self._cache[sub] = {
                "result": dict(result),
                "expires_at": datetime.utcnow() + timedelta(hours=1),
            }
            return dict(result)

        except HTTPException:
            raise
        except Exception as exc:
            logger.error("CrossAppAccessFlow failed: %s", exc)
            raise HTTPException(
                status_code=502,
                detail=f"Token exchange failed: {exc}",
            ) from exc

    # ------------------------------------------------------------------
    # Service Account — ROPG flow for elevated access
    # ------------------------------------------------------------------

    async def exchange_service_account(self, scopes: list[str] | None = None) -> dict:
        """Get an elevated MCP token via Resource Owner Password Grant + XAA.

        1. ROPG at Org AS with service account creds → id_token
        2. XAA: id_token → ID-JAG → elevated access_token at Custom AS

        Returns same dict shape as exchange().
        """
        if scopes is None:
            scopes = ["frontier:elevated"]

        cache_key = f"svc:{','.join(scopes)}"
        cached = self._cache.get(cache_key)
        if cached and cached["expires_at"] > datetime.utcnow():
            logger.info("Using cached service account token")
            return dict(cached["result"])

        logger.info("Service Account ROPG flow (scopes=%s)", scopes)

        try:
            org_token_endpoint = await self._get_org_token_endpoint()

            # Step 0: ROPG — get id_token for the service account
            logger.info("ROPG: authenticating service account at Org AS")
            async with httpx.AsyncClient() as http:
                resp = await http.post(
                    org_token_endpoint,
                    data={
                        "grant_type": "password",
                        "username": self.s.SERVICE_ACCOUNT_USERNAME,
                        "password": self.s.SERVICE_ACCOUNT_PASSWORD,
                        "client_id": self.s.OKTA_CLIENT_ID,
                        "client_secret": self.s.OKTA_CLIENT_SECRET,
                        "scope": "openid",
                    },
                    timeout=15,
                )
            if resp.status_code != 200:
                err = resp.json().get("error_description", resp.text)
                raise Exception(f"ROPG failed: {err}")

            ropg_tokens = resp.json()
            svc_id_token = ropg_tokens.get("id_token")
            if not svc_id_token:
                raise Exception("ROPG response missing id_token")

            svc_id_claims = self._extract_claims(svc_id_token)
            logger.info("ROPG succeeded for sub=%s", svc_id_claims.get("sub") if svc_id_claims else "?")

            # Steps 1-2: XAA with the service account's id_token
            agent_client = self._build_agent_client(audience=org_token_endpoint)
            target = CrossAppAccessTarget(
                issuer=self.s.OKTA_MCP_RESOURCE_SERVER_ISSUER,
            )
            flow = CrossAppAccessFlow(client=agent_client, target=target)

            logger.info("XAA step 1: svc id_token → ID-JAG at Org AS")
            await flow.start(
                token=svc_id_token,
                token_type="id_token",
                scope=scopes,
            )

            id_jag_claims = None
            ctx = flow._context
            if ctx and ctx.id_jag_token:
                id_jag_claims = self._extract_claims(ctx.id_jag_token.access_token)

            logger.info("XAA step 2: ID-JAG → elevated access_token at Custom AS")
            token = await flow.resume()

            access_token = token.access_token
            access_token_claims = self._extract_claims(access_token)
            logger.info("Service Account XAA succeeded")

            result = {
                "access_token": access_token,
                "id_token_claims": svc_id_claims,
                "id_jag_claims": id_jag_claims,
                "access_token_claims": access_token_claims,
            }
            self._cache[cache_key] = {
                "result": result,
                "expires_at": datetime.utcnow() + timedelta(hours=1),
            }
            return result

        except HTTPException:
            raise
        except Exception as exc:
            logger.error("Service Account flow failed: %s", exc)
            raise HTTPException(
                status_code=502,
                detail=f"Service account token exchange failed: {exc}",
            ) from exc
