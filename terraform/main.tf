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
  authentication_policy     = okta_app_signon_policy.atko_assistant_auth.id

  lifecycle {
    ignore_changes = [grant_types]
  }
}

# ── Enable ROPG grant type (not allowed at app creation time) ─────────────────
#
# Okta's API rejects "password" in grant_types on POST /api/v1/apps for web apps.
# We add it via a PUT after the app is created.

resource "terraform_data" "enable_ropg" {
  depends_on = [okta_app_oauth.atko_assistant_app]

  provisioner "local-exec" {
    command = <<-EOT
      curl -s -X PUT \
        "https://${var.okta_org_name}.${var.okta_base_url}/api/v1/apps/${okta_app_oauth.atko_assistant_app.id}" \
        -H "Authorization: SSWS ${var.okta_api_token}" \
        -H "Content-Type: application/json" \
        -d "$(curl -s "https://${var.okta_org_name}.${var.okta_base_url}/api/v1/apps/${okta_app_oauth.atko_assistant_app.id}" \
          -H "Authorization: SSWS ${var.okta_api_token}" \
          | python3 -c "
import json, sys
app = json.load(sys.stdin)
grants = app['settings']['oauthClient']['grant_types']
if 'password' not in grants:
    grants.append('password')
print(json.dumps(app))
")" > /dev/null
    EOT
  }
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
  priority        = 98
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

# ── Service Account User (ROPG) ──────────────────────────────────────────────
#
# Creates the service account user for elevated operations.
# The user authenticates via ROPG (password grant) and must be assigned
# to the OIDC app. Skip if service_account_email is not set.

resource "okta_user" "service_account" {
  count      = var.service_account_email != "" ? 1 : 0
  first_name = var.service_account_first_name
  last_name  = var.service_account_last_name
  login      = var.service_account_email
  email      = var.service_account_email
  password   = var.service_account_password
  status     = "ACTIVE"
}

resource "okta_app_user" "service_account_assignment" {
  count    = var.service_account_email != "" ? 1 : 0
  app_id   = okta_app_oauth.atko_assistant_app.id
  user_id  = okta_user.service_account[0].id
  username = var.service_account_email
}
