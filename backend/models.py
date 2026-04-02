from pydantic import BaseModel


class ChatMessage(BaseModel):
    role: str   # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    conversation_history: list[ChatMessage] = []


class TokenExchange(BaseModel):
    agent: str
    agent_name: str
    color: str
    success: bool
    access_denied: bool
    status: str             # "granted" | "denied"
    scopes: list[str]
    requested_scopes: list[str]
    error: str | None = None
    demo_mode: bool = False


class ChatResponse(BaseModel):
    response: str
    tool_calls: list[str] = []
    flow_events: list[str] = []
    token_exchanges: list[TokenExchange] = []
