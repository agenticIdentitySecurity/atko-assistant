"""
FastMCP server exposing SQLite database tools.

Started as a subprocess by the FastAPI backend.
Reads MCP_ACCESS_TOKEN from the environment and validates it against Okta
before serving any tool requests.

Token validation uses the synchronous httpx client so we can do it before
calling mcp.run() (which internally manages the asyncio event loop).
"""
import json
import logging
import os
import sys

import httpx
from jose import jwk, jwt as jose_jwt

from mcp.server.fastmcp import FastMCP

from mcp_server.database import Database

logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,  # log to stderr so stdout stays clean for stdio transport
    format="%(asctime)s [MCP] %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

mcp = FastMCP("Frontier DB")
db = Database()


# ---------------------------------------------------------------------------
# Synchronous token validation (runs before the event loop starts)
# ---------------------------------------------------------------------------

def _validate_token_sync(token: str) -> dict:
    """Validate the MCP access token against Okta's JWKS endpoint (sync)."""
    mcp_issuer = os.getenv("OKTA_MCP_RESOURCE_SERVER_ISSUER", "")
    audience = os.getenv("OKTA_MCP_AUDIENCE", "api://mcp-resource-server")

    jwks_uri = f"{mcp_issuer}/v1/keys"
    with httpx.Client(timeout=10) as client:
        resp = client.get(jwks_uri)
        resp.raise_for_status()
        jwks = resp.json()

    header = jose_jwt.get_unverified_header(token)
    kid = header.get("kid")
    pub_key = None
    for k in jwks.get("keys", []):
        if k.get("kid") == kid:
            pub_key = jwk.construct(k)
            break

    if pub_key is None:
        raise ValueError(f"No matching JWKS key for kid={kid}")

    claims = jose_jwt.decode(
        token,
        pub_key,
        algorithms=["RS256"],
        audience=audience,
        issuer=mcp_issuer,
    )

    # Extract and store scopes for tool-level gating
    scopes_raw = claims.get("scp") or claims.get("scope", [])
    if isinstance(scopes_raw, str):
        _token_scopes.update(scopes_raw.split())
    elif isinstance(scopes_raw, list):
        _token_scopes.update(scopes_raw)
    logger.info("Token scopes: %s", _token_scopes)

    return claims


# Global token scopes — populated during validation, checked by tools
_token_scopes: set[str] = set()


def _require_scope(scope: str) -> None:
    """Raise if the current token lacks the required scope."""
    if scope not in _token_scopes:
        raise PermissionError(f"Access denied — token missing required scope: {scope}")


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def query_customers(filter_email: str = "", limit: int = 10) -> str:
    """Query customer records.

    Args:
        filter_email: Optional substring to match against customer email.
        limit: Max rows to return (default 10).

    Returns:
        JSON array of customer objects.
    """
    sql = "SELECT id, name, email, country, created_at FROM customers"
    params: list = []
    if filter_email:
        sql += " WHERE email LIKE ?"
        params.append(f"%{filter_email}%")
    sql += f" ORDER BY id LIMIT {int(limit)}"
    rows = db.query(sql, params)
    return json.dumps(rows, indent=2, default=str)


@mcp.tool()
def query_orders(customer_id: int = 0, limit: int = 10) -> str:
    """Query order records.

    Args:
        customer_id: Filter by customer ID (0 = all customers).
        limit: Max rows to return (default 10).

    Returns:
        JSON array of order objects.
    """
    sql = "SELECT id, customer_id, order_date, status, total_amount FROM orders"
    params: list = []
    if customer_id:
        sql += " WHERE customer_id = ?"
        params.append(customer_id)
    sql += f" ORDER BY order_date DESC LIMIT {int(limit)}"
    rows = db.query(sql, params)
    return json.dumps(rows, indent=2, default=str)


@mcp.tool()
def get_customer_with_orders(customer_id: int) -> str:
    """Get a customer's profile together with their recent orders.

    Args:
        customer_id: The customer's ID.

    Returns:
        JSON object with 'customer' and 'orders' keys.
    """
    customers = db.query(
        "SELECT id, name, email, country FROM customers WHERE id = ?",
        [customer_id],
    )
    if not customers:
        return json.dumps({"error": f"No customer with id={customer_id}"})

    orders = db.query(
        """
        SELECT id, order_date, status, total_amount
        FROM orders
        WHERE customer_id = ?
        ORDER BY order_date DESC
        LIMIT 10
        """,
        [customer_id],
    )
    return json.dumps(
        {"customer": customers[0], "orders": orders},
        indent=2,
        default=str,
    )


@mcp.tool()
def search_products(search_term: str, limit: int = 10) -> str:
    """Search products by name or description.

    Args:
        search_term: Keyword to match against product name or description.
        limit: Max rows to return (default 10).

    Returns:
        JSON array of product objects.
    """
    rows = db.query(
        """
        SELECT id, name, description, price, stock
        FROM products
        WHERE name LIKE ? OR description LIKE ?
        LIMIT ?
        """,
        [f"%{search_term}%", f"%{search_term}%", int(limit)],
    )
    return json.dumps(rows, indent=2, default=str)


@mcp.tool()
def add_subscription(customer_id: int, service_name: str, plan: str = "Basic") -> str:
    """Add a streaming subscription for a customer. Requires elevated access.

    Args:
        customer_id: The customer's ID.
        service_name: Name of the service (e.g., "Paramount+", "Netflix").
        plan: Subscription plan (e.g., "Basic", "Premium").

    Returns:
        JSON object confirming the subscription was added.
    """
    _require_scope("frontier:elevated")
    try:
        db.conn.execute(
            "INSERT INTO subscriptions (customer_id, service_name, plan, status) VALUES (?, ?, ?, 'active')",
            (customer_id, service_name, plan),
        )
        db.conn.commit()
        return json.dumps({
            "success": True,
            "customer_id": customer_id,
            "service_name": service_name,
            "plan": plan,
            "status": "active",
        }, indent=2)
    except Exception as exc:
        return json.dumps({"success": False, "error": str(exc)})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    token = os.getenv("MCP_ACCESS_TOKEN")
    if not token:
        logger.error("MCP_ACCESS_TOKEN env var is required")
        sys.exit(1)

    logger.info("Validating MCP access token…")
    try:
        claims = _validate_token_sync(token)
        logger.info("Token valid — user sub: %s", claims.get("sub"))
    except Exception as exc:
        logger.error("Token validation failed: %s", exc)
        sys.exit(1)

    db.initialize()
    logger.info("Starting MCP stdio server")
    mcp.run(transport="stdio")
