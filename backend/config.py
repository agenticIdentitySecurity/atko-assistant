from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True)

    # Okta OIDC (consumer login)
    OKTA_ISSUER: str
    OKTA_CLIENT_ID: str
    OKTA_CLIENT_SECRET: str
    OKTA_REDIRECT_URI: str = "http://localhost:8000/auth/callback"

    # Okta Service App (for CrossAppAccessFlow — JWT Bearer client assertion)
    OKTA_SERVICE_CLIENT_ID: str
    OKTA_SERVICE_KEY_PATH: str  # path to RS256 private_key.pem
    OKTA_MCP_RESOURCE_SERVER_ISSUER: str  # issuer of the MCP resource server auth server
    OKTA_MCP_AUDIENCE: str = "api://mcp-resource-server"

    # Claude API
    ANTHROPIC_API_KEY: str

    # Session
    SESSION_SECRET_KEY: str

    # Database
    DATABASE_PATH: str = "./ai_agent.db"

    # MCP
    MCP_SERVER_SCRIPT: str = "mcp_server/server.py"


settings = Settings()
