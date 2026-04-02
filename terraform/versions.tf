terraform {
  required_version = ">= 1.6.0"

  required_providers {
    okta = {
      source  = "okta/okta"
      version = "~> 6.5"
    }
  }
}
