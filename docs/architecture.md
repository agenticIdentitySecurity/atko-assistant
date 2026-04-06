# Atko Assistant — Architecture

This document explains how the Atko Assistant demo works. Read this if you want to understand the system without setting it up.

For setup and deployment instructions, see [implementation.md](./implementation.md).

---

## System Overview

Atko Assistant is a single-agent AI system where a FastAPI backend orchestrates Claude (LLM) and a secured MCP server (Frontier DB). Consumer identity flows through every layer — the user's Okta identity is preserved all the way to the database query.

```
┌──────────────────────────────────────────────────────────────┐
│                     Consumer Browser                         │
│               (Vanilla JS + Tailwind CSS)                    │
└────────────────────────┬─────────────────────────────────────┘
                         │
                         │  1. Login via Okta OIDC
                         │  2. Query with Okta ID token
                         ▼
┌──────────────────────────────────────────────────────────────┐
│                  FastAPI Backend (Atko Assistant)             │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐    │
│  │  Auth  (/auth/login, /auth/callback, /auth/logout)   │    │
│  │  OktaAuth — Authorization Code + PKCE                │    │
│  └──────────────────────────────────────────────────────┘    │
│  ┌──────────────────────────────────────────────────────┐    │
│  │  API  (/api/me, /api/chat)                           │    │
│  │  Lazy token exchange — only when tools needed        │    │
│  └──────────────────────────────────────────────────────┘    │
│  ┌──────────────────────────────────────────────────────┐    │
│  │  Claude Agent  (backend/agent.py)                    │    │
│  │  Phase A: LLM call with static tool schemas          │    │
│  │  Phase B: CrossAppAccessFlow (if tools requested)    │    │
│  │  Phase C: MCP subprocess + tool execution            │    │
│  └──────────────────────────────────────────────────────┘    │
│                                                              │
└────────────────────────┬─────────────────────────────────────┘
                         │
                         │  Cross-App Access (on behalf of Consumer)
                         ▼
┌──────────────────────────────────────────────────────────────┐
│                          Okta                                │
│                                                              │
│   ┌─────────────────────┐   ┌──────────────────────────┐     │
│   │   Org Auth Server   │   │  Frontier MCP Auth Server │     │
│   │  (Step 1: ID-JAG)   │   │  (Step 2: MCP token)      │     │
│   └─────────────────────┘   └──────────────────────────┘     │
│                                                              │
│   ┌─────────────────────┐   ┌──────────────────────────┐     │
│   │    AI Agent         │   │    OIDC Application       │     │
│   │  (Directory→Agents) │   │  (consumer login)         │     │
│   └─────────────────────┘   └──────────────────────────┘     │
│                                                              │
└────────────────────────┬─────────────────────────────────────┘
                         │
                         │  Consumer-scoped MCP token
                         ▼
┌──────────────────────────────────────────────────────────────┐
│               Frontier DB MCP (subprocess, stdio)            │
│                                                              │
│  Validates token on startup via Okta JWKS                    │
│                                                              │
│   query_customers   │   query_orders       (frontier:read)   │
│   get_customer_with_orders   │   search_products             │
│   add_subscription  (requires frontier:elevated)             │
│                                                              │
│                    SQLite Database                           │
│      customers · products · orders · order_items ·           │
│      subscriptions                                           │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

---

## The Frontier DB MCP Tools

The Frontier DB MCP server exposes tools over the stdio transport. Claude selects and calls these tools based on the user's query. Tools are **scope-gated** — the MCP server checks the access token's scopes before executing.

| Tool | Required Scope | Purpose | Key Parameters |
|------|---------------|---------|----------------|
| `query_customers` | `frontier:read` | Filter customer records by email | `filter_email`, `limit` |
| `query_orders` | `frontier:read` | List orders, optionally by customer | `customer_id`, `limit` |
| `get_customer_with_orders` | `frontier:read` | Customer profile + order history | `customer_id` (required) |
| `search_products` | `frontier:read` | Full-text search on name/description | `search_term` (required), `limit` |
| `add_subscription` | `frontier:elevated` | Add a streaming subscription for a customer | `customer_id`, `service_name`, `plan` |

The database is pre-populated with sample data: 5 customers, 5 products, 10 orders with line items, and 6 subscriptions.

---

## Token Exchange Flow (ID-JAG)

This is the core of how Okta AI Agent Governance works. Atko Assistant never uses the consumer's session token directly to access Frontier DB — it exchanges it for a short-lived, scoped token.

### The Two-Step Exchange

```
Consumer logs in via Org Authorization Server
     │
     ▼
┌────────────────────────────────────────────────────────────┐
│  Step 1: ID Token → ID-JAG                                 │
│                                                            │
│  WHERE:  Org Authorization Server                          │
│          https://your-org.okta.com/oauth2/v1/token         │
│                                                            │
│  INPUT:  Consumer's ID token from OIDC login               │
│  OUTPUT: ID-JAG (Identity Assertion JWT)                   │
│                                                            │
│  The ID-JAG represents "Atko Assistant acting on behalf    │
│  of <Consumer>". Establishes delegation.                   │
│                                                            │
│  IMPORTANT: Step 1 always happens at the Org AS.           │
│  This is why OKTA_ORG_URL must be the Org AS URL.          │
└────────────────────────────────────────────────────────────┘
     │
     ▼
┌────────────────────────────────────────────────────────────┐
│  Step 2: ID-JAG → Frontier MCP Access Token                │
│                                                            │
│  WHERE:  Frontier MCP Custom Authorization Server          │
│          https://your-org.okta.com/oauth2/{aus...}/v1/token│
│                                                            │
│  INPUT:  ID-JAG from Step 1                                │
│  OUTPUT: Scoped access token (audience: api://mcp-resource-server) │
│                                                            │
│  Okta checks: Does this consumer's policy allow            │
│  frontier:read scope for this agent?                       │
└────────────────────────────────────────────────────────────┘
     │
     ▼
Frontier DB MCP server validates token and serves tool requests
```

### Why Two Steps?

1. **Step 1 establishes delegation** — the ID-JAG proves Atko Assistant is acting on behalf of a specific consumer, not autonomously.
2. **Step 2 enforces authorization** — the Frontier MCP auth server checks its access policies before granting any scopes.

This separation provides:
- A clear audit trail: every token exchange records *which agent* acted *for which user* at *what time*
- Revocation: removing a policy rule or revoking the consumer's assignment immediately stops access
- Scope minimization: the agent only receives `frontier:read`, never broader permissions

### Service Account Flow (Elevated Access)

When a tool requires elevated access (e.g., `add_subscription` needs `frontier:elevated`), the system automatically escalates to a service account:

```
Consumer asks "Add Paramount+ subscription"
     │
     ▼
┌────────────────────────────────────────────────────────────┐
│  Step 0: ROPG — Service Account Authentication             │
│                                                            │
│  WHERE:  Org Authorization Server                          │
│  GRANT:  Resource Owner Password (grant_type=password)     │
│                                                            │
│  INPUT:  Service account username + password               │
│  OUTPUT: Service account ID token                          │
│                                                            │
│  NOTE: ROPG is a temporary workaround. In production,      │
│  credentials must be vaulted and a more secure grant type   │
│  (e.g., Client Credentials) should be used when supported. │
└────────────────────────────────────────────────────────────┘
     │
     ▼
  Steps 1-2 follow the same XAA flow as consumer,
  but with the service account's ID token and
  requesting frontier:elevated scope instead of frontier:read
```

The elevated tool runs in a **separate MCP subprocess** with the elevated token. Consumer tools and elevated tools can execute in the same chat turn on different MCP sessions with different scopes.

---

## Lazy Token Exchange (Phase A → B → C)

A key design decision in this implementation: **the token exchange is deferred until Claude actually needs to call a tool**. This matches the natural sequence of the consumer flow diagram.

```
Phase A — First LLM call (no MCP, no token exchange yet)
─────────────────────────────────────────────────────────
  Consumer query arrives → Claude is called with static tool schemas
  Claude decides: does this query need database tools?

  If NO → return answer directly (zero Okta calls, zero MCP subprocess)
  If YES → proceed to Phase B

Phase B — Lazy Cross-App Access (okta-client-python SDK)
─────────────────────────────────────────────────────────
  CrossAppAccessFlow (from okta_client.oauth2auth) executes:
    flow.start(id_token)  →  ID-JAG (Step 1 at Org AS)
    flow.resume()         →  MCP access token (Step 2 at Frontier MCP AS)

  The SDK handles JWT assertion signing, metadata discovery, and
  audience routing automatically via LocalKeyProvider + JWTBearerClaims.

  Token is cached per consumer sub for 1 hour (TokenExchanger._cache)

Phase C — MCP tool execution
─────────────────────────────────────────────────────────
  MCP subprocess starts with MCP_ACCESS_TOKEN env var
  MCP server validates token via Okta JWKS on startup
  Claude's tool calls execute against Frontier DB
  Results returned to Claude → final response generated
```

### Full Sequence Diagram

```
Consumer    Okta         Atko Assistant      LLM      Frontier MCP   Frontier DB
    │          │                │              │             │               │
    │──login──►│                │              │             │               │
    │◄─token───│                │              │             │               │
    │          │                │              │             │               │
    │──query (with Okta token)──►              │             │               │
    │          │                │              │             │               │
    │          │                │──process────►│  (Phase A)  │               │
    │          │                │◄─tool calls──│             │               │
    │          │                │              │             │               │
    │          │◄─Cross-App Access (on behalf of Consumer)   │               │
    │          │────consumer-scoped token──────►             │               │
    │          │                │              │  (Phase B)  │               │
    │          │                │──request data (MCP token)──►               │
    │          │                │              │             │──query DB─────►│
    │          │                │              │             │◄──results──────│
    │          │                │◄─data response────────────┤   (Phase C)    │
    │          │                │──augment────►│             │               │
    │          │                │◄─final response            │               │
    │◄─display response─────────│              │             │               │
```

---

## Okta Components

### OIDC Application
The OAuth/OIDC app that consumers log into and that the service account uses for ROPG.

- **Grant types**: Authorization Code, Refresh Token, Token Exchange, Password (ROPG)
- **Password grant**: Not exposed in Okta Admin UI. Must be enabled via the [Apps API](https://developer.okta.com/docs/api/openapi/okta-management/management/tag/Application/) (`PUT /api/v1/apps/{appId}`) or Terraform (`okta_app_oauth` resource with `grant_types` including `"password"`)
- **PKCE**: S256 code challenge
- **Callback**: `http://localhost:8000/auth/callback` (local)
- **Purpose**: Issues the consumer's ID token after login

### AI Agent (Directory → AI Agents)
Registered in Okta's AI Agent Directory. Represents Atko Assistant's identity.

- **Authentication**: RS256 JWK private key (no client secret), identified by `OKTA_SERVICE_KEY_ID`
- **Purpose**: Performs the CrossAppAccessFlow on behalf of the consumer
- **Must be linked** to the OIDC application above
- **Must have a managed connection** to the Frontier MCP authorization server (authorizes the agent to request tokens for that resource)
- **Must be added** to "Assigned clients" on the Frontier MCP auth server policy

### Org Authorization Server
The main Okta authorization server (no custom path).

- **URL**: `https://your-org.okta.com` (configured as `OKTA_ORG_URL`)
- **Role**: OIDC login (issues ID token) and Step 1 of token exchange (issues ID-JAG)
- **Critical**: Users **must** log in via this server. Do not use a Custom AS URL as `OKTA_ORG_URL`.

### Frontier MCP Custom Authorization Server
A dedicated Okta Custom Authorization Server for the Frontier DB resource.

- **Audience**: `api://mcp-resource-server`
- **Scopes**: `frontier:read` (consumer), `frontier:elevated` (service account)
- **Access Policies**: "Allow Consumer Access" (frontier:read), "Service Account Rule" (frontier:elevated with ROPG + JWT Bearer + Token Exchange grants)
- **Role**: Step 2 of token exchange — issues the scoped MCP token
- **URL configured as**: `OKTA_MCP_RESOURCE_SERVER_ISSUER`

---

## Security Model

### What the Agent Never Sees
- Consumer's password
- Consumer's session cookie
- Long-lived credentials of any kind

### What the Agent Gets
- A short-lived access token scoped to `frontier:read` (consumer) or `frontier:elevated` (service account)
- Only after Okta confirms the relevant policy allows it
- Cached for 1 hour per user `sub` (`TokenExchanger._cache` in `backend/token_exchange.py`)

### MCP Server Validation
The Frontier DB MCP server (`mcp_server/server.py`) validates the `MCP_ACCESS_TOKEN` synchronously on startup before the event loop begins:

1. Fetches Okta's JWKS from `OKTA_MCP_RESOURCE_SERVER_ISSUER/v1/keys`
2. Verifies RS256 signature, audience, and issuer
3. If validation fails → process exits (no tools served)

### Audit Trail
Every token exchange is logged in Okta System Logs:
- Which AI Agent requested access
- On behalf of which consumer
- To which authorization server
- Which scopes were granted or denied
- Timestamp and IP

---

## Further Reading

- [Implementation Guide](./implementation.md) — Step-by-step local setup
- [Okta AI Agent Governance](https://developer.okta.com/docs/guides/ai-agent-governance/) — Official Okta docs
- [IETF ID-JAG Specification](https://datatracker.ietf.org/doc/draft-ietf-oauth-identity-assertion-authz-grant/) — Identity Assertion JWT Authorization Grant draft
