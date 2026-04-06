locals {
  okta_domain = "https://${var.okta_org_name}.${var.okta_base_url}"
}

# ── OIDC Web Application — consumer login ───────────────────────────────────

resource "okta_app_oauth" "atko_assistant_app" {
  label                     = "Atko Assistant"
  type                      = "web"
  grant_types               = ["authorization_code", "refresh_token", "urn:ietf:params:oauth:grant-type:token-exchange", "password"]
  redirect_uris             = [var.redirect_uri]
  post_logout_redirect_uris = ["${var.app_base_url}/login-page"]
  response_types            = ["code"]
  pkce_required             = true
  authentication_policy     = okta_app_signon_policy.atko_assistant_auth.id
}

# ── Authentication Policy — password-only for service account ROPG ──────────
#
# The service account uses ROPG which cannot do interactive MFA.
# This policy allows password-only auth for the service account group,
# with a catch-all rule for other users.

resource "okta_app_signon_policy" "atko_assistant_auth" {
  name        = "Atko Assistant Auth Policy"
  description = "Allows password-only login for the ROPG service account"
}

resource "okta_app_signon_policy_rule" "service_account_password_only" {
  policy_id       = okta_app_signon_policy.atko_assistant_auth.id
  name            = "Service Account — Password Only"
  priority        = 1
  factor_mode     = "1FA"
  constraints     = [jsonencode({ knowledge = { types = ["password"] } })]
  groups_included = var.service_account_group_ids
}

resource "okta_app_signon_policy_rule" "catch_all" {
  policy_id       = okta_app_signon_policy.atko_assistant_auth.id
  name            = "Catch-All — Default MFA"
  priority        = 99
  factor_mode     = "1FA"
  constraints     = [jsonencode({ knowledge = { types = ["password"] } })]
  groups_included = [data.okta_group.everyone.id]
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

# frontier:elevated scope — for service account operations (add_subscription etc.)
resource "okta_auth_server_scope" "frontier_elevated" {
  auth_server_id   = okta_auth_server.frontier_mcp.id
  name             = "frontier:elevated"
  description      = "Elevated access for service account operations"
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

# ── Service Account Rule ───────────────────────────────────────────────────
#
# Allows the service account to obtain frontier:elevated tokens via ROPG + XAA.
# ROPG authenticates at the Org AS; XAA step 2 uses JWT Bearer + Token Exchange
# at this Custom AS. The service account user must be in the "Everyone" group.
#
# NOTE: The OIDC app must also have the "password" grant type enabled.
# The Okta Admin UI does not expose this — Terraform sets it via the Apps API.

resource "okta_auth_server_policy_rule" "allow_service_account" {
  auth_server_id  = okta_auth_server.frontier_mcp.id
  policy_id       = okta_auth_server_policy.frontier_mcp_policy.id
  name            = "Service Account Rule"
  priority        = 2
  group_whitelist = [data.okta_group.everyone.id]
  scope_whitelist = ["frontier:elevated"]
  grant_type_whitelist = [
    "password",
    "urn:ietf:params:oauth:grant-type:jwt-bearer",
    "urn:ietf:params:oauth:grant-type:token-exchange",
  ]
}
