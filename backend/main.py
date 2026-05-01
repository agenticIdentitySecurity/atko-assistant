"""
FastAPI application — wires together Okta OIDC, token exchange, and the Claude agent.
"""
import logging
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from backend.agent import run_agent
from backend.auth import OktaAuth, require_user
from backend.config import settings
from backend.models import ChatRequest, ChatResponse
from backend.token_exchange import TokenExchanger

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Atko Assistant")

# Session middleware (cookie-based, signed with SESSION_SECRET_KEY)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SESSION_SECRET_KEY,
    session_cookie="session",
    https_only=settings.HTTPS_ONLY,
    same_site="lax",
)

okta = OktaAuth(settings)
exchanger = TokenExchanger(settings)

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    user = request.session.get("user")
    html_file = FRONTEND_DIR / "index.html"
    html = html_file.read_text()
    if not user:
        # Inject a login-wall overlay — simplest approach: just redirect
        return RedirectResponse(url="/login-page")
    return HTMLResponse(content=html)


@app.get("/login-page", response_class=HTMLResponse)
async def login_page():
    """Simple login landing page served before authentication."""
    html_file = FRONTEND_DIR / "login.html"
    if html_file.exists():
        return HTMLResponse(content=html_file.read_text())
    # Fallback: inline minimal page
    return HTMLResponse(content="""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <title>Login</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-50 flex items-center justify-center h-screen">
  <div class="bg-white rounded-2xl shadow-lg p-10 text-center max-w-sm w-full">
    <h1 class="text-2xl font-bold text-gray-900 mb-2">AI Agent Chat</h1>
    <p class="text-gray-500 mb-8">Sign in with your Okta account to continue.</p>
    <a href="/auth/login"
       class="block w-full py-3 bg-blue-600 hover:bg-blue-700 text-white font-semibold rounded-lg transition">
      Login with Okta
    </a>
  </div>
</body>
</html>""")


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------

@app.get("/auth/login")
async def auth_login(request: Request):
    """Redirect browser to Okta authorization endpoint."""
    url = await okta.authorization_url(request)
    return RedirectResponse(url=url)


@app.get("/auth/callback")
async def auth_callback(request: Request):
    """Handle Okta callback (query response_mode)."""
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    error = request.query_params.get("error")

    if error:
        raise HTTPException(status_code=400, detail=f"Okta error: {form.get('error_description', error)}")

    if state != request.session.get("oauth_state"):
        raise HTTPException(status_code=400, detail="State mismatch — possible CSRF")

    verifier = request.session.pop("pkce_verifier", "")
    request.session.pop("oauth_state", None)

    tokens = await okta.exchange_code(code, verifier)
    id_token = tokens.get("id_token")
    if not id_token:
        raise HTTPException(status_code=400, detail="No id_token in response")

    claims = await okta.validate_id_token(id_token, tokens.get("access_token"))

    request.session["user"] = {
        "sub": claims["sub"],
        "email": claims.get("email", ""),
        "name": claims.get("name", claims.get("email", "")),
    }
    request.session["id_token"] = id_token
    request.session["oidc_access_token"] = tokens.get("access_token", "")

    return RedirectResponse(url=settings.FRONTEND_URL, status_code=303)


@app.get("/auth/logout")
async def auth_logout(request: Request):
    id_token = request.session.get("id_token", "")
    request.session.clear()
    # Redirect to Okta's logout endpoint to end the Okta session too
    metadata = await okta._get_oidc_metadata()
    end_session_endpoint = metadata.get("end_session_endpoint")
    if end_session_endpoint and id_token:
        from urllib.parse import urlencode
        params = urlencode({
            "id_token_hint": id_token,
            "post_logout_redirect_uri": f"{settings.FRONTEND_URL}/login-page",
        })
        return RedirectResponse(url=f"{end_session_endpoint}?{params}")
    return RedirectResponse(url="/login-page")


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@app.get("/api/me")
async def me(user: dict = Depends(require_user)):
    return user


@app.post("/api/chat", response_model=ChatResponse)
async def chat(
    request: Request,
    body: ChatRequest,
    user: dict = Depends(require_user),
):
    id_token: str = request.session.get("id_token", "")
    oidc_access_token: str = request.session.get("oidc_access_token", "")
    if not id_token:
        raise HTTPException(status_code=401, detail="Session missing ID token")

    # Token exchange is now lazy — happens inside run_agent only when tools are needed.
    # These lists are populated in-place by run_agent so we can read them even on error.
    flow_events: list[str] = ["Query sent to Atko Assistant"]
    token_exchanges: list[dict] = []

    try:
        result = await run_agent(
            message=body.message,
            history=body.conversation_history,
            id_token=id_token,
            oidc_access_token=oidc_access_token,
            exchanger=exchanger,
            user=user,
            flow_events=flow_events,
            token_exchanges=token_exchanges,
        )
    except HTTPException as exc:
        # Token exchange or tool execution failed — return flow state to the frontend
        # so the Token Exchange panel can show the denied card.
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "detail": exc.detail,
                "flow_events": flow_events,
                "token_exchanges": token_exchanges,
            },
        )

    return ChatResponse(
        response=result["response"],
        tool_calls=result["tool_calls"],
        flow_events=result.get("flow_events", []),
        token_exchanges=result.get("token_exchanges", []),
        token_details=result.get("token_details"),
    )


# ---------------------------------------------------------------------------
# Static files (JS, CSS, etc. from frontend/)
# API routes and page routes above take precedence over this mount.
# ---------------------------------------------------------------------------

app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")
