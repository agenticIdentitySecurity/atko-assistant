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
Always present data clearly and concisely.
If you need multiple pieces of information, call the appropriate tools in sequence.
"""

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
]


async def run_agent(
    message: str,
    history: list[ChatMessage],
    id_token: str,
    oidc_access_token: str,
    exchanger: Any,
    flow_events: list[str],
    token_exchanges: list[dict],
) -> dict[str, Any]:
    """Run one chat turn with Claude + lazy MCP token exchange.

    Returns a dict: {"response": str, "tool_calls": list[str],
                     "flow_events": list[str], "token_exchanges": list[dict]}
    """
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

    first_response = _anthropic.messages.create(
        model=settings.ANTHROPIC_MODEL,
        max_tokens=2048,
        system=SYSTEM_PROMPT,
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
    # ------------------------------------------------------------------
    flow_events.append("Cross-App Access requested")
    logger.info("Performing token exchange (Cross-App Access)")

    try:
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
            "requested_scopes": ["frontier:read"],
            "error": exc.detail,
            "demo_mode": False,
        })
        flow_events.append("Token exchange denied by Okta governance policy")
        raise

    token_exchanges.append({
        "agent": "frontier_mcp",
        "agent_name": "Frontier MCP",
        "color": "#6366f1",
        "success": True,
        "access_denied": False,
        "status": "granted",
        "scopes": ["frontier:read"],
        "requested_scopes": ["frontier:read"],
        "error": None,
        "demo_mode": False,
    })
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
                        system=SYSTEM_PROMPT,
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
