from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True)

    # Okta Org AS — used for OIDC login and ID-JAG exchange (step 1 of XAA)
    OKTA_ORG_URL: str  # e.g. https://dev-xxxxx.okta.com (Org AS, no /oauth2/...)
    OKTA_CLIENT_ID: str
    OKTA_CLIENT_SECRET: str
    OKTA_REDIRECT_URI: str = "http://localhost:8000/auth/callback"

    # Okta AI Agent service app (for CrossAppAccessFlow — JWT Bearer client assertion)
    OKTA_SERVICE_CLIENT_ID: str
    OKTA_SERVICE_KEY_PATH: str  # path to RS256 private_key.pem
    OKTA_SERVICE_KEY_ID: str | None = None  # kid from Okta AI Agent key pair

    # Custom Authorization Server for the MCP Resource Server (step 2 of XAA)
    OKTA_MCP_RESOURCE_SERVER_ISSUER: str  # e.g. https://dev-xxxxx.okta.com/oauth2/my-as
    OKTA_MCP_AUDIENCE: str = "api://mcp-resource-server"

    # Service Account — used for ROPG elevated flow (add_subscription etc.)
    SERVICE_ACCOUNT_USERNAME: str = ""
    SERVICE_ACCOUNT_PASSWORD: str = ""

    # Claude API
    ANTHROPIC_API_KEY: str
    ANTHROPIC_BASE_URL: str | None = None  # set to route via LiteLLM or a proxy
    ANTHROPIC_MODEL: str = "claude-sonnet-4-6"

    # Session
    SESSION_SECRET_KEY: str

    # Database
    DATABASE_PATH: str = "./ai_agent.db"

    # MCP
    MCP_SERVER_SCRIPT: str = "mcp_server/server.py"


settings = Settings()
