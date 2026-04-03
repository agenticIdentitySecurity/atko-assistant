# Implementation Guide: Atko Assistant

This guide walks you through configuring Okta and running Atko Assistant locally.

For a conceptual overview of how the system works, see [architecture.md](./architecture.md).

---

## What You're Building

Atko Assistant is a local AI chat application that demonstrates **Okta AI Agent Governance**. It connects a FastAPI backend (Claude as the LLM) to a secured MCP resource server (Frontier DB) using Okta's Cross-App Access flow. The UI shows two live panels:

- **Identity Flow** — step-by-step trace of the token flow for each query
- **Token Exchanges** — per-exchange grant/deny cards showing which scopes were issued or blocked

The key demonstration: if Claude determines a query needs database tools, Atko Assistant performs a Cross-App Access token exchange on behalf of the logged-in consumer. If access is revoked in Okta, the Token Exchange panel shows a red "Denied" card without any code changes.

---

## Architecture Overview

See [architecture.md](./architecture.md) for full diagrams. The short version:

1. Consumer logs in → Okta issues an ID token
2. Consumer sends a query → Atko Assistant calls Claude (no MCP yet)
3. Claude requests tool calls → Atko Assistant performs Cross-App Access → Okta issues a consumer-scoped MCP token
4. Atko Assistant calls Frontier DB MCP with the scoped token → MCP queries SQLite
5. Claude augments its response with the data → displayed to consumer

---

## Prerequisites

- **Python 3.11+**
- **Okta developer account** — free at [developer.okta.com](https://developer.okta.com). Requires the AI Agent Governance feature (available on all developer orgs)
- **Anthropic API key** — [console.anthropic.com](https://console.anthropic.com)
- **Git**
- **Terraform >= 1.6** *(Option B only)* — [install](https://developer.hashicorp.com/terraform/install)

---

## Phase 1: Okta Configuration

Choose the setup option that works for you:

- **Option A: Manual Setup** — configure Okta through the Admin Console UI (15–20 min)
- **Option B: Automated Setup (Terraform)** — provision most resources automatically using an Okta API token; two manual steps still required

---

### Option A: Manual Setup (Okta Admin Console)

Complete all four steps below. Collect the values as you go — you will need them for your `.env` file.

#### Step 1: Create OIDC Application

This is the application your consumers log into.

1. In the Okta Admin Console, go to **Applications → Applications → Create App Integration**
2. Select **OIDC - OpenID Connect**, then **Web Application**
3. Configure:
   - **App integration name**: `Atko Assistant`
   - **Grant type**: check **Authorization Code** and **Refresh Token**
   - **Sign-in redirect URI**: `http://localhost:8000/auth/callback`
   - **Sign-out redirect URI**: `http://localhost:8000/login-page`
   - **Assignments**: Assign to the users (or groups) who will demo the app
4. Save and record:

| Value | Environment Variable |
|-------|---------------------|
| Client ID | `OKTA_CLIENT_ID` |
| Client Secret | `OKTA_CLIENT_SECRET` |

---

#### Step 2: Register the AI Agent

> **Important**: You must register the agent through **Directory → AI Agents**, not through Applications. This registers a proper workload principal in Okta's AI Agent Directory.

1. Go to **Directory → AI Agents → Register AI Agent**
2. Configure:
   - **Name**: `Atko Assistant Agent`
   - **Credentials**: Generate a new **RS256** key pair
3. Download the **private key** as `private_key.pem` — store it securely, you cannot retrieve it again
4. **Link to OIDC app**: On the agent detail page → **Linked applications** → link it to the `Atko Assistant` OIDC app
5. **Add Managed connection**: On the agent detail page → **Managed connections** → **Add connection** → select `Frontier MCP` authorization server, set scopes to **All**

   > **Critical**: Without this managed connection the Org AS returns `invalid_target` on token exchange. This authorizes the AI Agent to request tokens for the Frontier MCP resource server on behalf of users.

6. Record:

| Value | Environment Variable |
|-------|---------------------|
| Client ID shown on agent page | `OKTA_SERVICE_CLIENT_ID` |
| Key ID (`kid`) on the Credentials tab | `OKTA_SERVICE_KEY_ID` |
| Path to your downloaded PEM file | `OKTA_SERVICE_KEY_PATH` |

---

#### Step 3: Create the Frontier MCP Custom Authorization Server

This is the resource server that controls access to Frontier DB.

##### 3a. Create the Authorization Server

1. Go to **Security → API → Authorization Servers → Add Authorization Server**
2. Configure:
   - **Name**: `Frontier MCP`
   - **Audience**: `api://mcp-resource-server`
   - **Description**: `Authorization server for Frontier DB MCP resource`
3. Save and record:

| Value | Environment Variable |
|-------|---------------------|
| **Issuer URI** (shown on Metadata URI tab) | `OKTA_MCP_RESOURCE_SERVER_ISSUER` |

The issuer URI looks like: `https://dev-xxxxx.okta.com/oauth2/aus...`

##### 3b. Add the Scope

1. Go to the **Scopes** tab → **Add Scope**
2. Configure:
   - **Name**: `frontier:read`
   - **Display phrase**: `Read access to Frontier DB`
   - **Include in public metadata**: checked

##### 3c. Create an Access Policy

1. Go to the **Access Policies** tab → **Add Policy**
2. Configure:
   - **Name**: `Frontier MCP Policy`
   - **Assigned to**: Add both the **Atko Assistant Agent** (AI Agent entity) and **Atko Assistant** (OIDC app)

> **Critical**: Both the AI Agent entity AND the OIDC application must be in "Assigned clients". This is the most common cause of `no_matching_policy` errors.

##### 3d. Add a Policy Rule

1. Inside the policy, click **Add Rule**
2. Configure:
   - **Rule name**: `Allow Consumer Access`
   - **Grant type is**: Authorization Code, Token Exchange, JWT Bearer (check all three)
   - **User is**: Members of the following groups → **Everyone** (or a specific group if you want to demo denial)
   - **Scopes requested**: `frontier:read`
3. Save

---

#### Step 4: Record All Configuration Values

Before moving on, confirm you have all of these:

- [ ] `OKTA_ORG_URL` — your Okta org URL, **no auth server path** (e.g. `https://dev-xxxxx.okta.com`)
- [ ] `OKTA_CLIENT_ID` — from Step 1
- [ ] `OKTA_CLIENT_SECRET` — from Step 1
- [ ] `OKTA_SERVICE_CLIENT_ID` — from Step 2
- [ ] `OKTA_SERVICE_KEY_ID` — key ID (`kid`) from the AI Agent Credentials tab
- [ ] `OKTA_SERVICE_KEY_PATH` — local path to `private_key.pem` from Step 2
- [ ] `OKTA_MCP_RESOURCE_SERVER_ISSUER` — from Step 3 (includes the auth server ID in the path)
- [ ] `OKTA_MCP_AUDIENCE` — `api://mcp-resource-server` (default, unless you changed it)

> **Critical**: `OKTA_ORG_URL` must be the Org Authorization Server URL (e.g. `https://dev-xxxxx.okta.com`), **not** a Custom Authorization Server URL. Step 1 of the ID-JAG exchange always runs against the Org AS. If you use a Custom AS URL here, token exchange will fail with an `invalid_target` error.

---

### Option B: Automated Setup (Terraform)

The `terraform/` directory contains a Terraform configuration that automates most of the Okta setup. You still need to complete two manual steps (AI Agent registration and app-linking) because the Okta AI Agent Registry has no Terraform resource.

#### What Terraform automates

| Resource | Details |
|---|---|
| OIDC Web Application | `Atko Assistant` app with Authorization Code + Refresh Token, PKCE |
| Frontier MCP Custom Authorization Server | Audience: `api://mcp-resource-server` |
| `frontier:read` scope | On the Frontier MCP AS |
| Access policy | Assigned to both the OIDC app and AI Agent (`client_whitelist`) |
| Policy rule | Everyone group, `frontier:read`, all three grant types |

#### What still requires manual steps (cannot be done via Terraform)

> **Note**: The Okta AI Agent Registry (`Directory → AI Agents`) does not have a Terraform provider resource. These two steps must be done in the Okta Admin Console before or after `terraform apply`.

**Step 1 (before terraform apply) — Register the AI Agent:**

1. Go to **Directory → AI Agents → Register AI Agent**
2. Name: `Atko Assistant Agent`, Credentials: **RS256** key pair
3. Download `private_key.pem` — you cannot retrieve it again
4. Record the **Client ID** shown on the AI Agent page (you will need it as `okta_ai_agent_id` in `terraform.tfvars`)

**Step 2 (after terraform apply) — Link the OIDC app to the AI Agent:**

1. Go to **Directory → AI Agents → Atko Assistant Agent**
2. Under **Linked Applications**, add the `Atko Assistant` OIDC app that Terraform created

#### Prerequisites for Terraform

- [Terraform](https://developer.hashicorp.com/terraform/install) >= 1.6
- An Okta API token — **Security → API → Tokens** in the Okta Admin Console

#### Terraform workflow

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars — fill in okta_org_name, okta_api_token, okta_ai_agent_id
terraform init
terraform apply
```

After `terraform apply` succeeds, get your `.env` values:

```bash
# View the env snippet (client_secret excluded)
terraform output env_file_snippet

# Get the client secret separately (sensitive)
terraform output -raw okta_client_secret
```

Then complete the two manual steps above (link OIDC app to AI Agent), fill in `OKTA_SERVICE_CLIENT_ID` and `OKTA_SERVICE_KEY_PATH` in `.env`, and proceed to Phase 2.

---

## Phase 2: Local Setup

### Install Dependencies

```bash
git clone <repo-url>
cd ai-agent-app
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Configure Environment

Copy the example file and fill in all values:

```bash
cp .env.example .env
```

Edit `.env`:

```bash
# Okta Org AS (consumer login) — Step 1
OKTA_ORG_URL=https://dev-xxxxx.okta.com        # Org AS — no /oauth2/... path
OKTA_CLIENT_ID=0oa...
OKTA_CLIENT_SECRET=...
OKTA_REDIRECT_URI=http://localhost:8000/auth/callback

# Okta AI Agent — Step 2
OKTA_SERVICE_CLIENT_ID=wlp...
OKTA_SERVICE_KEY_PATH=./private_key.pem        # path to the PEM file you downloaded
OKTA_SERVICE_KEY_ID=<kid-from-credentials-tab> # key ID from AI Agent Credentials tab

# Frontier MCP Custom Auth Server — Step 3
OKTA_MCP_RESOURCE_SERVER_ISSUER=https://dev-xxxxx.okta.com/oauth2/aus...
OKTA_MCP_AUDIENCE=api://mcp-resource-server

# Claude / Anthropic
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_BASE_URL=https://llm.your-company.ai # optional: LiteLLM proxy or gateway
ANTHROPIC_MODEL=claude-sonnet-4-6              # model name (may differ behind a proxy)

# Session (generate with: python -c "import secrets; print(secrets.token_hex(32))")
SESSION_SECRET_KEY=<random-64-char-hex>

# Database and MCP (defaults are fine for local)
DATABASE_PATH=./ai_agent.db
MCP_SERVER_SCRIPT=mcp_server/server.py
```

Place `private_key.pem` (downloaded in Step 2) in the project root, or update `OKTA_SERVICE_KEY_PATH` to point to wherever you saved it.

### Database

No manual setup needed. The SQLite database initializes automatically the first time the MCP server starts, and sample data is inserted:

| Table | Sample records |
|-------|---------------|
| `customers` | 5 customers (Alice, Bob, Charlie, Diana, Eve) |
| `products` | 5 products (Laptop Pro, Wireless Mouse, Keyboard, Monitor, USB-C Hub) |
| `orders` | 10 orders across customers, various statuses |
| `order_items` | 14 line items linking orders to products |

---

## Phase 3: Run Locally

```bash
uvicorn backend.main:app --reload
```

Open **http://localhost:8000** in your browser.

The app redirects to the login page. Click **Login with Okta**, authenticate with a user assigned to the OIDC app, and you will be redirected to the chat interface.

---

## Demo Scenarios

### Scenario 1 — Data query (token exchange triggered)

**Query**: `"Show me all customers"`

**Expected**:
- Identity Flow panel shows 8 sequential steps
- "Cross-App Access requested" and "Consumer-scoped MCP token issued" appear **after** "Tool calls detected"
- Token Exchanges panel shows: `Frontier MCP  ✓ Granted  —  ID-JAG Exchange  —  frontier:read`

This demonstrates the lazy token exchange: Okta is not called until Claude decides it needs database tools.

### Scenario 2 — General question (no token exchange)

**Query**: `"What can you help me with?"`

**Expected**:
- Identity Flow panel shows only 2 steps: "LLM processing query" → "Final response ready (no tools needed)"
- Token Exchanges panel shows: "No exchanges yet"

This demonstrates that simple questions cost zero Okta calls and zero MCP subprocess starts.

### Scenario 3 — Access denied (governance)

To demonstrate access control:

1. In the Okta Admin Console, modify the Frontier MCP policy rule to exclude the logged-in user (e.g. change the group from Everyone to a specific group the user is not in)
2. Send a data query: `"List recent orders"`

**Expected**:
- Token Exchanges panel shows a red `✗ Denied` card for Frontier MCP
- Panel shows: "Blocked by Okta governance policy"
- No database data is returned

This demonstrates live governance: access can be revoked in Okta without touching any code.

---

## Environment Variables Reference

| Variable | Required | Description | Where to find it |
|----------|----------|-------------|-----------------|
| `OKTA_ORG_URL` | Yes | Okta Org AS URL — **no `/oauth2/...` path** | Your Okta org URL (e.g. `https://dev-xxxxx.okta.com`) |
| `OKTA_CLIENT_ID` | Yes | OIDC app client ID | Applications → your app → Client ID |
| `OKTA_CLIENT_SECRET` | Yes | OIDC app client secret | Applications → your app → Client Secrets |
| `OKTA_REDIRECT_URI` | Yes | OAuth callback URL | Set to `http://localhost:8000/auth/callback` |
| `OKTA_SERVICE_CLIENT_ID` | Yes | AI Agent client ID | Directory → AI Agents → your agent → Client ID |
| `OKTA_SERVICE_KEY_ID` | Yes | Key ID (`kid`) for the AI Agent RS256 key | Directory → AI Agents → your agent → Credentials tab |
| `OKTA_SERVICE_KEY_PATH` | Yes | Path to RS256 private key PEM | Where you saved the downloaded key |
| `OKTA_MCP_RESOURCE_SERVER_ISSUER` | Yes | Frontier MCP Custom AS issuer URL | Security → API → Frontier MCP → Issuer URI |
| `OKTA_MCP_AUDIENCE` | Yes | Frontier MCP token audience | `api://mcp-resource-server` (default) |
| `ANTHROPIC_API_KEY` | Yes | Claude API key | console.anthropic.com |
| `ANTHROPIC_BASE_URL` | No | LiteLLM proxy or gateway URL | Default: Anthropic direct API |
| `ANTHROPIC_MODEL` | No | Model name | Default: `claude-sonnet-4-6` |
| `SESSION_SECRET_KEY` | Yes | Cookie signing secret (32+ chars) | Generate: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `DATABASE_PATH` | No | SQLite file path | Default: `./ai_agent.db` |
| `MCP_SERVER_SCRIPT` | No | Path to MCP server script | Default: `mcp_server/server.py` |

---

## Troubleshooting

### `Token exchange failed` / `CrossAppAccessFlow failed`

**Cause**: The AI Agent is not correctly linked to the OIDC app, or the private key is wrong.

**Fix**:
- Confirm the AI Agent is linked to the OIDC app (Directory → AI Agents → your agent → Linked Applications)
- Verify `OKTA_SERVICE_KEY_PATH` points to the correct PEM file
- Ensure `OKTA_SERVICE_CLIENT_ID` matches the Client ID on the AI Agent page (not the OIDC app)

---

### `no_matching_policy`

**Cause**: The AI Agent entity or the OIDC app is not added to the "Assigned clients" on the Frontier MCP policy.

**Fix**:
- Security → API → Frontier MCP → Access Policies → your policy → Edit
- In "Assigned to", add both the AI Agent entity (`wlp...`) **and** the OIDC application (`0oa...`)

---

### `invalid_subject_token`

**Cause**: The OIDC app is not linked to the AI Agent.

**Fix**:
- Directory → AI Agents → your agent → Linked Applications → link the OIDC app

---

### `user_not_assigned`

**Cause**: The logged-in user is not assigned to the OIDC application.

**Fix**:
- Applications → Atko Assistant → Assignments → Assign the user or their group

---

### Issuer mismatch / token exchange fails with invalid issuer

**Cause**: `OKTA_ORG_URL` is set to a Custom Authorization Server URL instead of the Org AS.

**Fix**:
- `OKTA_ORG_URL` must be the bare org URL: `https://dev-xxxxx.okta.com`
- It must NOT contain `/oauth2/default` or any other auth server path
- Step 1 of the ID-JAG exchange discovers the Org AS token endpoint via `{OKTA_ORG_URL}/.well-known/oauth-authorization-server`

---

### MCP server exits immediately

**Cause**: The MCP access token is missing or fails Okta JWKS validation.

**Fix**:
- Check backend logs (`[MCP]` prefix) for the specific validation error
- Confirm `OKTA_MCP_RESOURCE_SERVER_ISSUER` matches the Issuer URI on the Custom AS settings page (not the metadata URL)
- Confirm `OKTA_MCP_AUDIENCE` matches the Audience field on the Custom AS

---

### `Session missing ID token` (401 on /api/chat)

**Cause**: The browser session expired or the session cookie was cleared.

**Fix**: Log out and log back in.

---

### `SESSION_SECRET_KEY` error on startup

**Cause**: The env var is missing or too short.

**Fix**: Generate a new value:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

---

## Verification Checklist

### Okta

Items marked **(manual only)** cannot be automated via Terraform and must be done in the UI regardless of which setup option you chose.

- [ ] OIDC application created with Authorization Code + Refresh Token grant types *(Terraform: `okta_app_oauth`)*
- [ ] Sign-in redirect URI set to `http://localhost:8000/auth/callback`
- [ ] AI Agent registered via **Directory → AI Agents** (not Applications) **(manual only)**
- [ ] AI Agent linked to the OIDC application **(manual only)**
- [ ] RS256 private key downloaded and saved **(manual only)**
- [ ] Frontier MCP Custom Authorization Server created *(Terraform: `okta_auth_server`)*
- [ ] Audience set to `api://mcp-resource-server`
- [ ] `frontier:read` scope added *(Terraform: `okta_auth_server_scope`)*
- [ ] Access policy created with AI Agent AND OIDC app in "Assigned clients" *(Terraform: `okta_auth_server_policy`)*
- [ ] Policy rule includes Token Exchange and JWT Bearer grant types *(Terraform: `okta_auth_server_policy_rule`)*

### Local Setup

- [ ] `.env` file created from `.env.example` with all values filled
- [ ] `private_key.pem` accessible at the path in `OKTA_SERVICE_KEY_PATH`
- [ ] `OKTA_ORG_URL` is the Org AS URL (no `/oauth2/...` path)
- [ ] `OKTA_SERVICE_KEY_ID` matches the `kid` on the AI Agent Credentials tab
- [ ] `uvicorn backend.main:app --reload` starts without errors
- [ ] *(Option B only)* `terraform apply` completed successfully; `terraform output env_file_snippet` used to populate `.env`

### Demo Verification

- [ ] `http://localhost:8000` redirects to login page
- [ ] Login with Okta completes and returns to chat
- [ ] Query `"Show me all customers"` triggers Identity Flow + Token Exchanges panels
- [ ] Token Exchanges shows `✓ Granted` for Frontier MCP with `frontier:read`
- [ ] Query `"What can you help me with?"` shows "No exchanges yet" in Token Exchanges panel
- [ ] "Cross-App Access requested" step appears **after** "Tool calls detected" in Identity Flow
