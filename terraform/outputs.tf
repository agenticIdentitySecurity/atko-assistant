###############################################################################
# Outputs — copy these into your .env file
# NOTE: okta_client_secret is sensitive. Use:
#   terraform output -raw okta_client_secret
###############################################################################

output "okta_issuer" {
  description = "Value for OKTA_ISSUER — the Org Authorization Server URL (no auth server path)"
  value       = "https://${var.okta_org_name}.${var.okta_base_url}"
}

output "okta_client_id" {
  description = "Value for OKTA_CLIENT_ID — the OIDC application client ID"
  value       = okta_app_oauth.atko_assistant_app.client_id
}

output "okta_client_secret" {
  description = "Value for OKTA_CLIENT_SECRET — retrieve with: terraform output -raw okta_client_secret"
  value       = okta_app_oauth.atko_assistant_app.client_secret
  sensitive   = true
}

output "okta_mcp_resource_server_issuer" {
  description = "Value for OKTA_MCP_RESOURCE_SERVER_ISSUER — the Frontier MCP Custom AS issuer URL"
  value       = okta_auth_server.frontier_mcp.issuer
}

output "env_file_snippet" {
  description = "Ready-to-paste .env snippet (client_secret omitted — retrieve separately)"
  value       = <<-EOT

    # ── Okta OIDC (consumer login) ──────────────────────────────────────
    OKTA_ISSUER=https://${var.okta_org_name}.${var.okta_base_url}
    OKTA_CLIENT_ID=${okta_app_oauth.atko_assistant_app.client_id}
    OKTA_CLIENT_SECRET=$(terraform output -raw okta_client_secret)
    OKTA_REDIRECT_URI=${var.redirect_uri}

    # ── Okta AI Agent (fill in after completing manual AI Agent steps) ──
    OKTA_SERVICE_CLIENT_ID=<paste AI Agent Client ID here>
    OKTA_SERVICE_KEY_PATH=./private_key.pem

    # ── Frontier MCP Custom Auth Server ─────────────────────────────────
    OKTA_MCP_RESOURCE_SERVER_ISSUER=${okta_auth_server.frontier_mcp.issuer}
    OKTA_MCP_AUDIENCE=api://mcp-resource-server

  EOT
}
