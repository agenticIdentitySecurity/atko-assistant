variable "okta_org_name" {
  description = "Okta org subdomain (e.g. dev-123456 from https://dev-123456.okta.com)"
  type        = string
}

variable "okta_base_url" {
  description = "Okta base URL: okta.com for production orgs, oktapreview.com for preview orgs"
  type        = string
  default     = "okta.com"
}

variable "okta_api_token" {
  description = "Okta API token — Security → API → Tokens in the Okta Admin Console"
  type        = string
  sensitive   = true
}

variable "okta_ai_agent_id" {
  description = <<-EOT
    Client ID of the AI Agent registered in Okta.
    Must be created manually first: Directory → AI Agents → Register AI Agent.
    The Client ID starts with 'wlp_' or '0oa_' and is shown on the AI Agent detail page.
  EOT
  type        = string
}

variable "redirect_uri" {
  description = "OIDC sign-in redirect URI for the local app"
  type        = string
  default     = "http://localhost:8000/auth/callback"
}

variable "app_base_url" {
  description = "Base URL of the local app (used for post-logout redirect)"
  type        = string
  default     = "http://localhost:8000"
}
