# Atko Assistant

A sample B2C chatbot demonstrating **Okta for AI Agents** with identity security powered by Cross-App Access.

Atko Assistant is a consumer-facing AI chat application where a Claude-powered agent queries a secured database (Frontier DB) on behalf of authenticated users. Every database access goes through Okta's Cross-App Access (XAA) token exchange, ensuring the AI agent operates with scoped, consumer-specific permissions — never with its own elevated privileges.

## What It Demonstrates

- **Consumer OIDC Login** — Users authenticate via Okta (Authorization Code + PKCE)
- **AI Agent Identity** — The agent is registered in Okta's AI Agent Directory with its own RS256 credentials
- **Cross-App Access (XAA)** — Two-step token exchange: ID Token → ID-JAG → scoped Access Token
- **Lazy Token Exchange** — Okta is only called when the LLM decides it needs database tools
- **Live Token Inspector** — Collapsible panel showing decoded claims at each step of the XAA flow
- **Governance in Real-Time** — Revoke access in Okta and the agent is immediately denied, no code changes needed

## Architecture

```
Consumer → Okta OIDC Login → ID Token
    ↓
Consumer Query → Claude LLM (Phase A)
    ↓
Claude needs tools → Cross-App Access (Phase B)
    ├── Step 1: ID Token → ID-JAG (Org AS)
    └── Step 2: ID-JAG → Access Token (Custom AS)
    ↓
Frontier DB MCP Server → SQLite Query (Phase C)
    ↓
Claude augments response → Consumer sees results
```

See [docs/architecture.md](docs/architecture.md) for the full system diagram and [docs/implementation.md](docs/implementation.md) for setup instructions.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Frontend** | Vanilla HTML/JS, Tailwind CSS (CDN) |
| **Backend** | Python, FastAPI, Uvicorn |
| **LLM** | Claude (Anthropic API) |
| **MCP Server** | FastMCP (stdio transport), SQLite |
| **Auth & Identity** | Okta OIDC (PKCE), Okta AI Agent Directory |
| **Token Exchange** | okta-client-python SDK (`CrossAppAccessFlow`) |
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
