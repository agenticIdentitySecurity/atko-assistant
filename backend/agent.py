"""
Claude AI Agent with MCP tool use — lazy token exchange.

Flow (matches sequence diagram):
  1. Call Claude first with static tool schemas (no MCP yet, no token exchange yet)
  2. If Claude returns tool_use, THEN perform Cross-App Access token exchange
  3. Start MCP subprocess with the consumer-scoped token
  4. Execute tool calls, continue agentic loop
  5. Return final response with flow_events and token_exchanges
"""
import logging
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

import anthropic
from fastapi import HTTPException
from jose import jwt as jose_jwt
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from backend.config import settings
from backend.models import ChatMessage

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are Atko Assistant, a helpful AI assistant with access to a customer database (Frontier DB).
Use the provided tools to look up customers, orders, and products when needed.
You can also add streaming subscriptions (e.g. Paramount+, Netflix) for customers using the add_subscription tool.
Always present data clearly and concisely.
If you need multiple pieces of information, call the appropriate tools in sequence.
"""

# Tools that require elevated (service account) access via ROPG
ELEVATED_TOOLS = {"add_subscription"}

_anthropic = anthropic.Anthropic(
    api_key=settings.ANTHROPIC_API_KEY,
    **({"base_url": settings.ANTHROPIC_BASE_URL} if settings.ANTHROPIC_BASE_URL else {}),
)

# Static tool schemas — defined here so Claude can be called before MCP starts.
# These match the tools registered in mcp_server/server.py.
STATIC_TOOL_SCHEMAS = [
    {
        "name": "query_customers",
        "description": (
            "Query customer records.\n\n"
            "Args:\n"
            "    filter_email: Optional substring to match against customer email.\n"
            "    limit: Max rows to return (default 10).\n\n"
            "Returns:\n"
            "    JSON array of customer objects."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "filter_email": {"type": "string"},
                "limit": {"type": "integer"},
            },
        },
    },
    {
        "name": "query_orders",
        "description": (
            "Query order records.\n\n"
            "Args:\n"
            "    customer_id: Filter by customer ID (0 = all customers).\n"
            "    limit: Max rows to return (default 10).\n\n"
            "Returns:\n"
            "    JSON array of order objects."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "integer"},
                "limit": {"type": "integer"},
            },
        },
    },
    {
        "name": "get_customer_with_orders",
        "description": (
            "Get a customer's profile together with their recent orders.\n\n"
            "Args:\n"
            "    customer_id: The customer's ID.\n\n"
            "Returns:\n"
            "    JSON object with 'customer' and 'orders' keys."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "integer"},
            },
            "required": ["customer_id"],
        },
    },
    {
        "name": "search_products",
        "description": (
            "Search products by name or description.\n\n"
            "Args:\n"
            "    search_term: Keyword to match against product name or description.\n"
            "    limit: Max rows to return (default 10).\n\n"
            "Returns:\n"
            "    JSON array of product objects."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "search_term": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["search_term"],
        },
    },
    {
        "name": "add_subscription",
        "description": (
            "Add a streaming subscription for a customer. Requires elevated service account access.\n\n"
            "Args:\n"
            "    customer_id: The customer's ID.\n"
            "    service_name: Name of the service (e.g., 'Paramount+', 'Netflix').\n"
            "    plan: Subscription plan (e.g., 'Basic', 'Premium').\n\n"
            "Returns:\n"
            "    JSON object confirming the subscription was added."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "integer"},
                "service_name": {"type": "string"},
                "plan": {"type": "string"},
            },
            "required": ["customer_id", "service_name"],
        },
    },
]


def _ensure_customer_exists(user: dict) -> None:
    """Ensure the logged-in user exists as a customer in the demo database."""
    email = user.get("email", "")
    name = user.get("name", email)
    if not email:
        return
    try:
        conn = sqlite3.connect(settings.DATABASE_PATH)
        cur = conn.cursor()
        cur.execute("SELECT id FROM customers WHERE email = ?", (email,))
        if not cur.fetchone():
            cur.execute(
                "INSERT INTO customers (name, email, country) VALUES (?, ?, ?)",
                (name, email, "USA"),
            )
            conn.commit()
            logger.info("Auto-created customer for logged-in user: %s", email)
        conn.close()
    except Exception as exc:
        logger.warning("Could not ensure customer exists: %s", exc)


async def _run_elevated_tool(
    tool_name: str,
    tool_input: dict,
    exchanger: Any,
    flow_events: list[str],
    token_exchanges: list[dict],
    exchange_result: dict,
) -> str:
    """Execute a single elevated tool in a separate MCP subprocess with service account token."""
    flow_events.append("Elevated access required — Service Account ROPG")
    logger.info("Elevated tool %s → starting service account flow", tool_name)

    try:
        svc_result = await exchanger.exchange_service_account(scopes=["frontier:elevated"])
        elevated_token = svc_result["access_token"]
        # Update exchange_result so token_details reflects the elevated flow
        exchange_result.update({
            "id_token_claims": svc_result.get("id_token_claims"),
            "id_jag_claims": svc_result.get("id_jag_claims"),
            "access_token_claims": svc_result.get("access_token_claims"),
        })
    except HTTPException as exc:
        token_exchanges.append({
            "agent": "frontier_mcp",
            "agent_name": "Frontier MCP (Elevated)",
            "color": "#f59e0b",
            "success": False,
            "access_denied": True,
            "status": "denied",
            "scopes": [],
            "requested_scopes": ["frontier:elevated"],
            "error": exc.detail,
            "demo_mode": False,
        })
        flow_events.append("Elevated token exchange denied")
        return f"Error: Elevated access denied — {exc.detail}"

    token_exchanges.append({
        "agent": "frontier_mcp",
        "agent_name": "Frontier MCP (Elevated)",
        "color": "#f59e0b",
        "success": True,
        "access_denied": False,
        "status": "granted",
        "scopes": ["frontier:elevated"],
        "requested_scopes": ["frontier:elevated"],
        "error": None,
        "demo_mode": False,
    })
    flow_events.append("Elevated MCP token issued (Service Account)")

    # Start a separate MCP subprocess with the elevated token
    project_root = str(Path(__file__).parent.parent)
    env = {**os.environ}
    env["PYTHONPATH"] = project_root + os.pathsep + env.get("PYTHONPATH", "")
    env["MCP_ACCESS_TOKEN"] = elevated_token
    env["OKTA_ORG_URL"] = settings.OKTA_ORG_URL
    env["OKTA_MCP_RESOURCE_SERVER_ISSUER"] = settings.OKTA_MCP_RESOURCE_SERVER_ISSUER
    env["OKTA_MCP_AUDIENCE"] = settings.OKTA_MCP_AUDIENCE
    env["DATABASE_PATH"] = settings.DATABASE_PATH

    server_params = StdioServerParameters(
        command=sys.executable,
        args=[settings.MCP_SERVER_SCRIPT],
        env=env,
    )

    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as elevated_session:
                await elevated_session.initialize()
                result = await elevated_session.call_tool(tool_name, tool_input)
                content_text = result.content[0].text if result.content else "No result"
                flow_events.append("Elevated tool executed successfully")
                return content_text
    except Exception as exc:
        logger.error("Elevated tool %s failed: %s", tool_name, exc)
        flow_events.append(f"Elevated tool error: {exc}")
        return f"Error: {exc}"


async def run_agent(
    message: str,
    history: list[ChatMessage],
    id_token: str,
    oidc_access_token: str,
    exchanger: Any,
    user: dict,
    flow_events: list[str],
    token_exchanges: list[dict],
) -> dict[str, Any]:
    """Run one chat turn with Claude + lazy MCP token exchange.

    Returns a dict: {"response": str, "tool_calls": list[str],
                     "flow_events": list[str], "token_exchanges": list[dict]}
    """
    # Ensure the logged-in user has a customer record in the demo DB
    _ensure_customer_exists(user)

    # Build message list
    messages: list[dict] = [
        {"role": m.role, "content": m.content} for m in history
    ]
    messages.append({"role": "user", "content": message})

    tool_names_used: list[str] = []

    # ------------------------------------------------------------------
    # Phase A — First Claude call (no MCP, no token exchange yet)
    # ------------------------------------------------------------------
    flow_events.append("LLM processing query")
    logger.info("Calling Claude (phase A — no MCP yet)")

    # Inject logged-in user context so Claude auto-resolves "me" / "my account"
    user_name = user.get("name") or user.get("email", "")
    user_email = user.get("email", "")
    system_with_user = (
        f"{SYSTEM_PROMPT}\n"
        f"The currently logged-in consumer is: {user_name} (email: {user_email}). "
        f"When they refer to themselves, their account, or don't specify a customer, "
        f"look up this consumer by email using query_customers with filter_email."
    )

    first_response = _anthropic.messages.create(
        model=settings.ANTHROPIC_MODEL,
        max_tokens=2048,
        system=system_with_user,
        tools=STATIC_TOOL_SCHEMAS,
        messages=messages,
    )

    if first_response.stop_reason != "tool_use":
        # No tools needed — return immediately, no token exchange
        final_text = "".join(
            block.text for block in first_response.content if hasattr(block, "text")
        )
        flow_events.append("Final response ready (no tools needed)")
        try:
            id_claims = jose_jwt.get_unverified_claims(id_token)
        except Exception:
            id_claims = None
        return {
            "response": final_text.strip(),
            "tool_calls": [],
            "flow_events": flow_events,
            "token_exchanges": token_exchanges,
            "token_details": {
                "oidc_client_id": settings.OKTA_CLIENT_ID,
                "agent_client_id": settings.OKTA_SERVICE_CLIENT_ID,
                "id_token_claims": id_claims,
            },
        }

    # Claude wants to call tools
    tool_names_in_first = [
        block.name for block in first_response.content if block.type == "tool_use"
    ]
    flow_events.append(f"Tool calls detected: {tool_names_in_first}")
    logger.info("Tool calls requested: %s", tool_names_in_first)

    # ------------------------------------------------------------------
    # Phase B — Lazy Cross-App Access token exchange
    # Detect if any tool requires elevated access → use ROPG service account
    # ------------------------------------------------------------------
    needs_elevated = bool(set(tool_names_in_first) & ELEVATED_TOOLS)

    if needs_elevated:
        flow_events.append("Elevated access required — Service Account ROPG")
        logger.info("Elevated tool detected, using service account ROPG flow")
        requested_scopes = ["frontier:elevated"]
    else:
        flow_events.append("Cross-App Access requested")
        requested_scopes = ["frontier:read"]

    logger.info("Performing token exchange (scopes=%s)", requested_scopes)

    try:
        if needs_elevated:
            exchange_result = await exchanger.exchange_service_account(scopes=requested_scopes)
        else:
            exchange_result = await exchanger.exchange(id_token, oidc_access_token)
        mcp_token = exchange_result["access_token"]
    except HTTPException as exc:
        token_exchanges.append({
            "agent": "frontier_mcp",
            "agent_name": "Frontier MCP",
            "color": "#6366f1",
            "success": False,
            "access_denied": True,
            "status": "denied",
            "scopes": [],
            "requested_scopes": requested_scopes,
            "error": exc.detail,
            "demo_mode": False,
        })
        flow_events.append("Token exchange denied by Okta governance policy")
        raise

    exchange_label = "Service Account ROPG → XAA" if needs_elevated else "Consumer XAA"
    token_exchanges.append({
        "agent": "frontier_mcp",
        "agent_name": "Frontier MCP",
        "color": "#f59e0b" if needs_elevated else "#6366f1",
        "success": True,
        "access_denied": False,
        "status": "granted",
        "scopes": requested_scopes,
        "requested_scopes": requested_scopes,
        "error": None,
        "demo_mode": False,
    })
    if needs_elevated:
        flow_events.append("Elevated MCP token issued (Service Account)")
    else:
        flow_events.append("Consumer-scoped MCP token issued")

    # ------------------------------------------------------------------
    # Phase C — MCP agentic loop
    # ------------------------------------------------------------------
    project_root = str(Path(__file__).parent.parent)
    env = {**os.environ}
    env["PYTHONPATH"] = project_root + os.pathsep + env.get("PYTHONPATH", "")
    env["MCP_ACCESS_TOKEN"] = mcp_token
    env["OKTA_ORG_URL"] = settings.OKTA_ORG_URL
    env["OKTA_MCP_RESOURCE_SERVER_ISSUER"] = settings.OKTA_MCP_RESOURCE_SERVER_ISSUER
    env["OKTA_MCP_AUDIENCE"] = settings.OKTA_MCP_AUDIENCE
    env["DATABASE_PATH"] = settings.DATABASE_PATH

    server_params = StdioServerParameters(
        command=sys.executable,
        args=[settings.MCP_SERVER_SCRIPT],
        env=env,
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Seed the loop with the first tool_use response from phase A
            pending_response = first_response
            augmented = False

            while True:
                if pending_response.stop_reason == "tool_use":
                    assistant_content = pending_response.content
                    messages.append({"role": "assistant", "content": assistant_content})

                    tool_results = []
                    for block in assistant_content:
                        if block.type == "tool_use":
                            tool_names_used.append(block.name)
                            flow_events.append(f"Frontier MCP: calling {block.name}")
                            logger.info("Calling tool %s with %s", block.name, block.input)

                            # Elevated tool → run in separate MCP with elevated token
                            if block.name in ELEVATED_TOOLS:
                                content_text = await _run_elevated_tool(
                                    block.name, block.input, exchanger,
                                    flow_events, token_exchanges, exchange_result,
                                )
                            else:
                                try:
                                    result = await session.call_tool(block.name, block.input)
                                    content_text = (
                                        result.content[0].text
                                        if result.content
                                        else "No result"
                                    )
                                    flow_events.append("Frontier DB results returned")
                                except Exception as exc:
                                    logger.error("Tool %s failed: %s", block.name, exc)
                                    content_text = f"Error: {exc}"
                                    flow_events.append(f"Frontier DB error: {exc}")

                            tool_results.append(
                                {
                                    "type": "tool_result",
                                    "tool_use_id": block.id,
                                    "content": content_text,
                                }
                            )

                    messages.append({"role": "user", "content": tool_results})

                    if not augmented:
                        flow_events.append("Augmenting response with data")
                        augmented = True

                    # Next Claude call
                    pending_response = _anthropic.messages.create(
                        model=settings.ANTHROPIC_MODEL,
                        max_tokens=2048,
                        system=system_with_user,
                        tools=STATIC_TOOL_SCHEMAS,
                        messages=messages,
                    )
                    continue

                # end_turn — extract final text
                final_text = "".join(
                    block.text
                    for block in pending_response.content
                    if hasattr(block, "text")
                )
                break

    flow_events.append("Final response ready")

    # If elevated tools ran, exchange_result was updated with svc claims
    elevated_used = "id_token_claims" in exchange_result
    if elevated_used:
        id_claims = exchange_result.get("id_token_claims")
    else:
        try:
            id_claims = jose_jwt.get_unverified_claims(id_token)
        except Exception:
            id_claims = None

    return {
        "response": final_text.strip(),
        "tool_calls": tool_names_used,
        "flow_events": flow_events,
        "token_exchanges": token_exchanges,
        "token_details": {
            "oidc_client_id": settings.OKTA_CLIENT_ID,
            "agent_client_id": settings.OKTA_SERVICE_CLIENT_ID,
            "id_token_claims": id_claims,
            "id_jag_claims": exchange_result.get("id_jag_claims"),
            "access_token_claims": exchange_result.get("access_token_claims"),
        },
    }
