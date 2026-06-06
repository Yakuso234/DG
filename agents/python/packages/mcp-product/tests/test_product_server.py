"""Tests for ecommerce-mcp-product server.

Two tiers:
- Registration smoke tests (no DB) — verify tool names are registered and
  the ASGI app is importable. These always run in CI.
- Integration tests (DB via testcontainers) — verify actual SQL queries against
  a real Postgres container with the production schema. Marked `integration`.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
import asyncpg

from ecommerce_mcp_product.server import mcp, app, _get_pool


# ─────────────────────── Registration smoke ─────────────────────────────────


def test_mcp_server_name() -> None:
    assert mcp.name == "product-discovery-mcp"


def test_tool_names_registered() -> None:
    """All 5 product tools must be discoverable without a DB connection."""
    tool_names = {t.name for t in mcp._tool_manager.list_tools()}
    expected = {
        "search_products",
        "get_product_details",
        "compare_products",
        "get_trending_products",
        "get_price_history",
    }
    assert expected == tool_names


def test_asgi_app_importable() -> None:
    """app must be a callable ASGI app (uvicorn entry-point check)."""
    assert callable(app)


def test_get_pool_raises_before_startup() -> None:
    """_get_pool() must fail loudly if called before lifespan starts."""
    with pytest.raises(RuntimeError, match="DB pool not initialized"):
        _get_pool()


# ─────────────────────── Integration (live DB) ──────────────────────────────


@pytest.fixture
async def product_id(postgres_pool: asyncpg.Pool) -> str:
    """Insert a minimal product row and return its id."""
    async with postgres_pool.acquire() as conn:
        # Insert a seller first (users table)
        seller_id = await conn.fetchval(
            """INSERT INTO users (email, name, role, password_hash)
               VALUES ('seller@test.com', 'Test Seller', 'seller', 'hash')
               ON CONFLICT (email) DO UPDATE SET name = EXCLUDED.name
               RETURNING id"""
        )
        pid = await conn.fetchval(
            """INSERT INTO products
                   (name, category, brand, price, original_price, rating,
                    review_count, description, seller_id, is_active)
               VALUES ('Widget Pro', 'Electronics', 'Acme', 99.99, 129.99, 4.5,
                       10, 'A fine widget', $1, TRUE)
               ON CONFLICT DO NOTHING
               RETURNING id""",
            seller_id,
        )
        if pid is None:
            pid = await conn.fetchval(
                "SELECT id FROM products WHERE name = 'Widget Pro' LIMIT 1"
            )
        return str(pid)


@pytest_asyncio.fixture
async def _patched_pool(postgres_pool: asyncpg.Pool, monkeypatch: pytest.MonkeyPatch):
    """Patch the module-level _pool so tool functions use the test container."""
    import ecommerce_mcp_product.server as srv
    monkeypatch.setattr(srv, "_pool", postgres_pool)
    yield


@pytest.mark.integration
async def test_search_products_returns_results(
    product_id: str,
    _patched_pool: None,
) -> None:
    from ecommerce_mcp_product.server import search_products

    results = await search_products(query="Widget")
    assert isinstance(results, list)
    assert any(r["id"] == product_id for r in results)


@pytest.mark.integration
async def test_get_product_details_found(
    product_id: str,
    _patched_pool: None,
) -> None:
    from ecommerce_mcp_product.server import get_product_details

    result = await get_product_details(product_id=product_id)
    assert "error" not in result
    assert result["id"] == product_id
    assert result["name"] == "Widget Pro"
    assert isinstance(result["in_stock"], bool)


@pytest.mark.integration
async def test_get_product_details_not_found(
    _patched_pool: None,
) -> None:
    from ecommerce_mcp_product.server import get_product_details

    result = await get_product_details(product_id="00000000-0000-0000-0000-000000000000")
    assert "error" in result


@pytest.mark.integration
async def test_search_products_no_results(
    _patched_pool: None,
) -> None:
    from ecommerce_mcp_product.server import search_products

    results = await search_products(query="zzz_no_such_product_xyz")
    assert isinstance(results, list)
    assert results == []


@pytest.mark.integration
async def test_compare_products_invalid_count(
    _patched_pool: None,
) -> None:
    from ecommerce_mcp_product.server import compare_products

    result = await compare_products(product_ids=["only-one"])
    assert result[0].get("error") is not None


@pytest.mark.integration
async def test_get_price_history_no_history(
    product_id: str,
    _patched_pool: None,
) -> None:
    from ecommerce_mcp_product.server import get_price_history

    result = await get_price_history(product_id=product_id, days=30)
    assert "error" not in result
    assert result["product_id"] == product_id
    # No price_history rows seeded → summary field present
    assert "current_price" in result
