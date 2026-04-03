locals {
  okta_domain = "https://${var.okta_org_name}.${var.okta_base_url}"
}

# ── OIDC Web Application — consumer login ───────────────────────────────────

resource "okta_app_oauth" "atko_assistant_app" {
  label                     = "Atko Assistant"
  type                      = "web"
  grant_types               = ["authorization_code", "refresh_token", "urn:ietf:params:oauth:grant-type:token-exchange"]
  redirect_uris             = [var.redirect_uri]
  post_logout_redirect_uris = ["${var.app_base_url}/login-page"]
  response_types            = ["code"]
  pkce_required             = true
}

# ── Frontier MCP Custom Authorization Server ────────────────────────────────

resource "okta_auth_server" "frontier_mcp" {
  name        = "Frontier MCP"
  description = "Authorization server for Frontier DB MCP resource"
  audiences   = ["api://mcp-resource-server"]
}

# frontier:read scope
resource "okta_auth_server_scope" "frontier_read" {
  auth_server_id   = okta_auth_server.frontier_mcp.id
  name             = "frontier:read"
  description      = "Read access to Frontier DB"
  metadata_publish = "ALL_CLIENTS"
}

# ── Access Policy ────────────────────────────────────────────────────────────
#
# client_whitelist must include BOTH the OIDC app (for Authorization Code)
# AND the AI Agent (for Token Exchange / JWT Bearer).
# The AI Agent is created manually in the Okta UI (Directory → AI Agents)
# and its client ID is provided via var.okta_ai_agent_id.

resource "okta_auth_server_policy" "frontier_mcp_policy" {
  auth_server_id   = okta_auth_server.frontier_mcp.id
  name             = "Frontier MCP Policy"
  description      = "Controls access to Frontier DB MCP"
  priority         = 1
  client_whitelist = [okta_app_oauth.atko_assistant_app.id, var.okta_ai_agent_id]
}

# ── Policy Rule ──────────────────────────────────────────────────────────────
#
# group_whitelist requires group IDs, not the string "EVERYONE".
# Look up the built-in Everyone group by name.

data "okta_group" "everyone" {
  name = "Everyone"
}

resource "okta_auth_server_policy_rule" "allow_consumer_access" {
  auth_server_id  = okta_auth_server.frontier_mcp.id
  policy_id       = okta_auth_server_policy.frontier_mcp_policy.id
  name            = "Allow Consumer Access"
  priority        = 1
  group_whitelist = [data.okta_group.everyone.id]
  scope_whitelist = ["frontier:read"]
  grant_type_whitelist = [
    "authorization_code",
    "urn:ietf:params:oauth:grant-type:jwt-bearer",
    "urn:ietf:params:oauth:grant-type:token-exchange",
  ]
}
