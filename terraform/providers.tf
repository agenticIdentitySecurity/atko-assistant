provider "okta" {
  # Credentials can also be set via environment variables:
  #   OKTA_ORG_NAME, OKTA_BASE_URL, OKTA_API_TOKEN
  org_name  = var.okta_org_name
  base_url  = var.okta_base_url
  api_token = var.okta_api_token
}
