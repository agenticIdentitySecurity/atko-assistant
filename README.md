# Atko Assistant

A sample B2C chatbot demonstrating **Okta for AI Agents** with identity security powered by Cross-App Access.

Atko Assistant is a consumer-facing AI chat application where a Claude-powered agent queries a secured database (Frontier DB) on behalf of authenticated users. Every database access goes through Okta's Cross-App Access (XAA) token exchange, ensuring the AI agent operates with scoped, consumer-specific permissions — never with its own elevated privileges.

## What It Demonstrates

- **Consumer OIDC Login** — Users authenticate via Okta (Authorization Code + PKCE)
- **AI Agent Identity** — The agent is registered in Okta's AI Agent Directory with its own RS256 credentials
- **Cross-App Access (XAA)** — Two-step token exchange: ID Token → ID-JAG → scoped Access Token
- **Scope-Based Access Control** — Consumer tools get `frontier:read`; elevated tools (e.g., add subscription) automatically escalate to a service account with `frontier:elevated`
- **Lazy Token Exchange** — Okta is only called when the LLM decides it needs database tools
- **Live Token Inspector** — Collapsible panel showing decoded claims at each step of the XAA flow
- **Governance in Real-Time** — Revoke access in Okta and the agent is immediately denied, no code changes needed

## Two Flows

### Flow 1: Consumer (frontier:read)
```
Consumer → Okta OIDC Login → ID Token
    → Claude LLM → needs read-only tools
    → XAA: ID Token → ID-JAG → Access Token (frontier:read)
    → Frontier DB: query_customers, query_orders, search_products
```

### Flow 2: Service Account — Elevated (frontier:elevated)
```
Consumer asks to add a subscription
    → Claude LLM → needs add_subscription (elevated tool)
    → ROPG: Service account authenticates → ID Token
    → XAA: ID Token → ID-JAG → Access Token (frontier:elevated)
    → Frontier DB: add_subscription executes with elevated scope
```

> **Note**: The ROPG (Resource Owner Password Grant) flow for the service account is a temporary workaround. In production, service account credentials must be vaulted and the flow should migrate to a more secure grant type (e.g., Client Credentials) when supported by Okta for this use case.

See [docs/architecture.md](docs/architecture.md) for the full system diagram and [docs/implementation.md](docs/implementation.md) for setup instructions.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Frontend** | Vanilla HTML/JS, Tailwind CSS (CDN) |
| **Backend** | Python, FastAPI, Uvicorn |
| **LLM** | Claude (Anthropic API) |
| **MCP Server** | FastMCP (stdio transport), SQLite |
| **Auth & Identity** | Okta OIDC (PKCE), Okta AI Agent Directory, ROPG (service account) |
| **Token Exchange** | okta-client-python SDK (`CrossAppAccessFlow`), scope-gated MCP tools |
| **Infrastructure** | Terraform (Okta provider) for automated setup |

## Okta Components

| Component | Purpose |
|-----------|---------|
| **OIDC Application** | Consumer login (Authorization Code + PKCE) |
| **AI Agent** | Registered identity for Atko Assistant (Directory → AI Agents) |
| **Org Authorization Server** | Issues ID-JAG tokens (step 1 of XAA) |
| **Custom Authorization Server** | Issues scoped MCP access tokens (step 2 of XAA) |

## Quick Start

```bash
# Clone and install
git clone https://github.com/agenticIdentitySecurity/atko-assistant.git
cd atko-assistant
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Configure Okta and environment (see docs/implementation.md)
cp .env.example .env
# Edit .env with your Okta values

# Run
uvicorn backend.main:app --reload
# Open http://localhost:8000
```

See the full [Implementation Guide](docs/implementation.md) for Okta configuration (manual or Terraform).

## Project Structure

```
├── backend/
│   ├── main.py              # FastAPI app, auth routes, /api/chat
│   ├── agent.py             # Claude agentic loop with lazy XAA
│   ├── auth.py              # Okta OIDC (PKCE) login
│   ├── token_exchange.py    # CrossAppAccessFlow via okta-client-python
│   ├── config.py            # Pydantic settings from .env
│   └── models.py            # Request/response schemas
├── frontend/
│   ├── index.html           # Chat UI + Token Inspector panel
│   ├── app.js               # Vanilla JS client
│   └── login.html           # Login landing page
├── mcp_server/
│   ├── server.py            # FastMCP server (Frontier DB tools)
│   ├── database.py          # SQLite with sample data
│   └── schema.py            # DB schema definitions
├── terraform/               # Automated Okta setup
├── docs/
│   ├── architecture.md      # System design and token flow
│   └── implementation.md    # Step-by-step setup guide
└── .env.example             # Environment variable template
```

## License

This project is provided as a sample for educational and demonstration purposes.
