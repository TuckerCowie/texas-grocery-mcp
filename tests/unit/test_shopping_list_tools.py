"""Tests for shopping list tools."""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture(autouse=True)
def reset_auth_state():
    """Reset auth state before each test."""
    from texas_grocery_mcp.auth.session import _reset_auth_state
    _reset_auth_state()
    yield
    _reset_auth_state()


# ---------------------------------------------------------------------------
# shopping_list_get
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_shopping_list_get_requires_auth():
    """shopping_list_get should require authentication."""
    from texas_grocery_mcp.tools.shopping_list import shopping_list_get

    with patch("texas_grocery_mcp.tools.shopping_list.is_authenticated", return_value=False):
        result = await shopping_list_get()

    assert result["auth_required"] is True
    assert "instructions" in result


# ---------------------------------------------------------------------------
# shopping_list_add
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_shopping_list_add_requires_auth():
    """shopping_list_add should require authentication."""
    from texas_grocery_mcp.tools.shopping_list import shopping_list_add

    with patch("texas_grocery_mcp.tools.shopping_list.is_authenticated", return_value=False):
        result = await shopping_list_add(product_id="931316")

    assert result["auth_required"] is True
    assert "instructions" in result


@pytest.mark.asyncio
async def test_shopping_list_add_without_confirm_returns_preview():
    """shopping_list_add without confirm should return a preview dict."""
    from texas_grocery_mcp.tools.shopping_list import shopping_list_add

    with patch("texas_grocery_mcp.tools.shopping_list.is_authenticated", return_value=True):
        result = await shopping_list_add(product_id="931316", confirm=False)

    assert result["preview"] is True
    assert result["action"] == "add_to_shopping_list"
    assert result["product_id"] == "931316"
    assert result["quantity"] == 1
    assert "confirm" in result["message"].lower()


@pytest.mark.asyncio
async def test_shopping_list_add_preview_includes_quantity():
    """Preview should reflect the requested quantity."""
    from texas_grocery_mcp.tools.shopping_list import shopping_list_add

    with patch("texas_grocery_mcp.tools.shopping_list.is_authenticated", return_value=True):
        result = await shopping_list_add(product_id="931316", quantity=3, confirm=False)

    assert result["preview"] is True
    assert result["quantity"] == 3
    assert "3" in result["message"]


@pytest.mark.asyncio
async def test_shopping_list_add_with_quantity_calls_single_add():
    """shopping_list_add with quantity > 1 should call add once with the quantity."""
    from texas_grocery_mcp.tools.shopping_list import shopping_list_add

    mock_lists_response = {
        "getShoppingListsV2": {
            "thisPage": {
                "sort": "CATEGORY",
                "sortDirection": "ASC",
                "totalCount": 1,
                "page": 1,
                "size": 20,
            },
            "nextPage": None,
            "lists": [
                {
                    "id": "list-uuid-1",
                    "name": "My List",
                    "totalItemCount": 1,
                    "created": "2024-01-01T00:00:00Z",
                    "updated": "2024-01-01T00:00:00Z",
                    "isActive": True,
                    "fulfillment": None,
                }
            ],
            "header": {
                "id": "list-uuid-1",
                "metadata": {"role": "OWNER", "shoppingListVisibilityLevel": "PRIVATE"},
            },
        }
    }

    mock_items_response = {
        "getShoppingListV2": {
            "id": "list-uuid-1",
            "name": "My List",
            "itemPage": {
                "items": [
                    {
                        "id": "item-uuid-1",
                        "product": {"id": "931316", "fullDisplayName": "Test Product"},
                        "quantity": 3,
                        "itemPrice": {
                            "totalAmount": 9.99,
                            "listPrice": 9.99,
                            "salePrice": 9.99,
                            "onSale": False,
                        },
                        "groupHeader": None,
                    }
                ]
            },
        }
    }

    mock_client = AsyncMock()
    mock_client.get_shopping_lists = AsyncMock(return_value=mock_lists_response)
    mock_client.add_to_shopping_list = AsyncMock(return_value={"addToShoppingListV2": {}})
    mock_client.get_shopping_list_items = AsyncMock(return_value=mock_items_response)

    with (
        patch("texas_grocery_mcp.tools.shopping_list.is_authenticated", return_value=True),
        patch("texas_grocery_mcp.tools.shopping_list._get_client", return_value=mock_client),
    ):
        result = await shopping_list_add(product_id="931316", quantity=3, confirm=True)

    assert result["success"] is True
    assert result["verified"] is True
    assert result["quantity"] == 3
    mock_client.add_to_shopping_list.assert_called_once_with(
        list_id="list-uuid-1", product_id="931316", quantity=3
    )


# ---------------------------------------------------------------------------
# shopping_list_remove
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_shopping_list_remove_requires_auth():
    """shopping_list_remove should require authentication."""
    from texas_grocery_mcp.tools.shopping_list import shopping_list_remove

    with patch("texas_grocery_mcp.tools.shopping_list.is_authenticated", return_value=False):
        result = await shopping_list_remove(product_id="931316")

    assert result["auth_required"] is True
    assert "instructions" in result


MOCK_LISTS_RESPONSE = {
    "getShoppingListsV2": {
        "thisPage": {
            "sort": "CATEGORY",
            "sortDirection": "ASC",
            "totalCount": 1,
            "page": 1,
            "size": 20,
        },
        "nextPage": None,
        "lists": [
            {
                "id": "list-uuid-1",
                "name": "My List",
                "totalItemCount": 1,
                "created": "2024-01-01T00:00:00Z",
                "updated": "2024-01-01T00:00:00Z",
                "isActive": True,
                "fulfillment": None,
            }
        ],
        "header": {
            "id": "list-uuid-1",
            "metadata": {"role": "OWNER", "shoppingListVisibilityLevel": "PRIVATE"},
        },
    }
}

MOCK_ITEMS_RESPONSE = {
    "getShoppingListV2": {
        "id": "list-uuid-1",
        "name": "My List",
        "itemPage": {
            "items": [
                {
                    "id": "item-uuid-abc",
                    "quantity": 1,
                    "groupHeader": "Dairy",
                    "itemPrice": {
                        "totalAmount": 3.99,
                        "listPrice": 3.99,
                        "salePrice": 3.99,
                        "onSale": False,
                    },
                    "product": {"id": "931316", "fullDisplayName": "Whole Milk 1 Gallon"},
                },
            ]
        },
    }
}


@pytest.mark.asyncio
async def test_shopping_list_remove_without_confirm_returns_preview():
    """shopping_list_remove without confirm should fetch list items and return preview with name."""
    from texas_grocery_mcp.tools.shopping_list import shopping_list_remove

    mock_client = AsyncMock()
    mock_client.get_shopping_lists = AsyncMock(return_value=MOCK_LISTS_RESPONSE)
    mock_client.get_shopping_list_items = AsyncMock(return_value=MOCK_ITEMS_RESPONSE)

    with (
        patch("texas_grocery_mcp.tools.shopping_list.is_authenticated", return_value=True),
        patch("texas_grocery_mcp.tools.shopping_list._get_client", return_value=mock_client),
    ):
        result = await shopping_list_remove(product_id="931316", confirm=False)

    assert result["preview"] is True
    assert result["action"] == "remove_from_shopping_list"
    assert result["product_id"] == "931316"
    assert result["item_id"] == "item-uuid-abc"
    assert result["name"] == "Whole Milk 1 Gallon"
    assert "confirm" in result["message"].lower()


@pytest.mark.asyncio
async def test_shopping_list_remove_product_not_on_list_returns_error():
    """shopping_list_remove should return an error when product is not on the list."""
    from texas_grocery_mcp.tools.shopping_list import shopping_list_remove

    mock_items_other_product = {
        "getShoppingListV2": {
            "id": "list-uuid-1",
            "name": "My List",
            "itemPage": {
                "items": [
                    {
                        "id": "item-uuid-xyz",
                        "quantity": 1,
                        "groupHeader": "Pantry",
                        "itemPrice": {
                            "totalAmount": 2.99,
                            "listPrice": 2.99,
                            "salePrice": 2.99,
                            "onSale": False,
                        },
                        "product": {"id": "111111", "fullDisplayName": "Some Other Product"},
                    },
                ]
            },
        }
    }

    mock_client = AsyncMock()
    mock_client.get_shopping_lists = AsyncMock(return_value=MOCK_LISTS_RESPONSE)
    mock_client.get_shopping_list_items = AsyncMock(return_value=mock_items_other_product)

    with (
        patch("texas_grocery_mcp.tools.shopping_list.is_authenticated", return_value=True),
        patch("texas_grocery_mcp.tools.shopping_list._get_client", return_value=mock_client),
    ):
        result = await shopping_list_remove(product_id="931316", confirm=False)

    assert result.get("error") is True
    assert result["code"] == "PRODUCT_NOT_ON_LIST"
    assert "931316" in result["message"]


# ---------------------------------------------------------------------------
# _resolve_list_id
# ---------------------------------------------------------------------------

def test_resolve_list_id_finds_list_by_name():
    """_resolve_list_id should match a list by name (case-insensitive)."""
    from texas_grocery_mcp.tools.shopping_list import _resolve_list_id

    result = {
        "getShoppingListsV2": {
            **MOCK_LISTS_RESPONSE["getShoppingListsV2"],
            "lists": [
                {
                    **MOCK_LISTS_RESPONSE["getShoppingListsV2"]["lists"][0],
                    "name": "This Week",
                }
            ],
        }
    }

    list_id, err = _resolve_list_id(result, "this week")
    assert list_id == "list-uuid-1"
    assert err is None


def test_resolve_list_id_returns_error_when_name_not_found():
    """_resolve_list_id should return an error message when the named list doesn't exist."""
    from texas_grocery_mcp.tools.shopping_list import _resolve_list_id

    list_id, err = _resolve_list_id(MOCK_LISTS_RESPONSE, "Nonexistent List")
    assert list_id is None
    assert err is not None
    assert "Nonexistent List" in err


def test_resolve_list_id_falls_back_to_first_when_no_name():
    """_resolve_list_id should return the first list when no name is requested."""
    from texas_grocery_mcp.tools.shopping_list import _resolve_list_id

    with patch("texas_grocery_mcp.tools.shopping_list.StateManager") as mock_sm:
        mock_sm.get_default_shopping_list_name.return_value = None
        list_id, err = _resolve_list_id(MOCK_LISTS_RESPONSE)

    assert list_id == "list-uuid-1"
    assert err is None


# ---------------------------------------------------------------------------
# shopping_list_add_many
# ---------------------------------------------------------------------------

VALID_ITEMS = [
    {"product_id": "111111", "quantity": 2},
    {"product_id": "222222", "quantity": 1},
]


@pytest.mark.asyncio
async def test_shopping_list_add_many_requires_auth():
    """shopping_list_add_many should require authentication."""
    from texas_grocery_mcp.tools.shopping_list import shopping_list_add_many

    with patch("texas_grocery_mcp.tools.shopping_list.is_authenticated", return_value=False):
        result = await shopping_list_add_many(items=VALID_ITEMS)

    assert result["auth_required"] is True
    assert "instructions" in result


@pytest.mark.asyncio
async def test_shopping_list_add_many_without_confirm_returns_preview():
    """shopping_list_add_many without confirm should return a preview."""
    from texas_grocery_mcp.tools.shopping_list import shopping_list_add_many

    with patch("texas_grocery_mcp.tools.shopping_list.is_authenticated", return_value=True):
        result = await shopping_list_add_many(items=VALID_ITEMS, confirm=False)

    assert result["preview"] is True
    assert result["count"] == len(VALID_ITEMS)
    assert "confirm" in result["message"].lower()


MOCK_ITEMS_AFTER_MANY = {
    "getShoppingListV2": {
        "id": "list-uuid-1",
        "name": "My List",
        "itemPage": {
            "items": [
                {
                    "id": "item-uuid-1",
                    "quantity": 2,
                    "groupHeader": None,
                    "itemPrice": {
                        "totalAmount": 5.98,
                        "listPrice": 2.99,
                        "salePrice": 2.99,
                        "onSale": False,
                    },
                    "product": {"id": "111111", "fullDisplayName": "Product One"},
                },
                {
                    "id": "item-uuid-2",
                    "quantity": 1,
                    "groupHeader": None,
                    "itemPrice": {
                        "totalAmount": 1.99,
                        "listPrice": 1.99,
                        "salePrice": 1.99,
                        "onSale": False,
                    },
                    "product": {"id": "222222", "fullDisplayName": "Product Two"},
                },
            ]
        },
    }
}


@pytest.mark.asyncio
async def test_shopping_list_add_many_success():
    """shopping_list_add_many should verify items and return enriched success data."""
    from texas_grocery_mcp.tools.shopping_list import shopping_list_add_many

    mock_client = AsyncMock()
    mock_client.get_shopping_lists = AsyncMock(return_value=MOCK_LISTS_RESPONSE)
    mock_client.add_to_shopping_list = AsyncMock(return_value={"addToShoppingListV2": {}})
    mock_client.get_shopping_list_items = AsyncMock(return_value=MOCK_ITEMS_AFTER_MANY)

    with (
        patch("texas_grocery_mcp.tools.shopping_list.is_authenticated", return_value=True),
        patch("texas_grocery_mcp.tools.shopping_list._get_client", return_value=mock_client),
    ):
        result = await shopping_list_add_many(items=VALID_ITEMS, confirm=True)

    assert result["success"] is True
    assert result["summary"]["added"] == len(VALID_ITEMS)
    assert result["summary"]["failed"] == 0
    assert "total_cost" in result["summary"]
    assert mock_client.add_to_shopping_list.call_count == len(VALID_ITEMS)
    # Verify enriched fields are present on each added item
    assert result["added"][0]["name"] == "Product One"
    assert "unit_price" in result["added"][0]
    assert "total_price" in result["added"][0]


@pytest.mark.asyncio
async def test_shopping_list_add_many_verification_failed_moves_item_to_failed():
    """shopping_list_add_many should move items to failed if not found in list after add."""
    from texas_grocery_mcp.tools.shopping_list import shopping_list_add_many

    # Items response only contains one of the two products (111111 missing)
    items_missing_one = {
        "getShoppingListV2": {
            "id": "list-uuid-1",
            "name": "My List",
            "itemPage": {
                "items": [
                    {
                        "id": "item-uuid-2",
                        "quantity": 1,
                        "groupHeader": None,
                        "itemPrice": {
                            "totalAmount": 1.99,
                            "listPrice": 1.99,
                            "salePrice": 1.99,
                            "onSale": False,
                        },
                        "product": {"id": "222222", "fullDisplayName": "Product Two"},
                    }
                ]
            },
        }
    }

    mock_client = AsyncMock()
    mock_client.get_shopping_lists = AsyncMock(return_value=MOCK_LISTS_RESPONSE)
    mock_client.add_to_shopping_list = AsyncMock(return_value={"addToShoppingListV2": {}})
    mock_client.get_shopping_list_items = AsyncMock(return_value=items_missing_one)

    with (
        patch("texas_grocery_mcp.tools.shopping_list.is_authenticated", return_value=True),
        patch("texas_grocery_mcp.tools.shopping_list._get_client", return_value=mock_client),
    ):
        result = await shopping_list_add_many(items=VALID_ITEMS, confirm=True)

    # One item verified, one not found → PARTIAL_FAILURE
    assert result["success"] is False
    assert result["code"] == "PARTIAL_FAILURE"
    assert result["summary"]["added"] == 1
    assert result["summary"]["failed"] == 1
    failed = result["failed"]
    assert any(f["code"] == "VERIFICATION_FAILED" for f in failed)


# ---------------------------------------------------------------------------
# shopping_list_add_with_retry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shopping_list_add_with_retry_requires_auth():
    """shopping_list_add_with_retry should require authentication."""
    from texas_grocery_mcp.tools.shopping_list import shopping_list_add_with_retry

    with patch("texas_grocery_mcp.tools.shopping_list.is_authenticated", return_value=False):
        result = await shopping_list_add_with_retry(product_id="931316")

    assert result["auth_required"] is True
    assert "instructions" in result


@pytest.mark.asyncio
async def test_shopping_list_add_with_retry_without_confirm_returns_preview():
    """shopping_list_add_with_retry without confirm should return a preview."""
    from texas_grocery_mcp.tools.shopping_list import shopping_list_add_with_retry

    with patch("texas_grocery_mcp.tools.shopping_list.is_authenticated", return_value=True):
        result = await shopping_list_add_with_retry(product_id="931316", confirm=False)

    assert result["preview"] is True
    assert result["product_id"] == "931316"


@pytest.mark.asyncio
async def test_shopping_list_add_with_retry_succeeds_without_retry():
    """shopping_list_add_with_retry should return success if first add succeeds."""
    from texas_grocery_mcp.tools.shopping_list import shopping_list_add_with_retry

    success_result = {
        "success": True,
        "verified": True,
        "action": "add_to_shopping_list",
        "product_id": "931316",
        "list_id": "list-uuid-1",
        "quantity": 1,
        "message": "Added 1x product 931316 to shopping list (verified)",
    }

    with (
        patch("texas_grocery_mcp.tools.shopping_list.is_authenticated", return_value=True),
        patch(
            "texas_grocery_mcp.tools.shopping_list.shopping_list_add",
            new=AsyncMock(return_value=success_result),
        ),
    ):
        result = await shopping_list_add_with_retry(product_id="931316", confirm=True)

    assert result["success"] is True
    assert result["verified"] is True


@pytest.mark.asyncio
async def test_shopping_list_add_with_retry_auto_corrects_product_id():
    """shopping_list_add_with_retry should search and retry when first add is not verified."""
    from texas_grocery_mcp.tools.shopping_list import shopping_list_add_with_retry

    not_verified_result = {
        "error": True,
        "code": "SHOPPING_LIST_ADD_NOT_VERIFIED",
        "product_id": "wrong-id",
        "quantity": 1,
        "message": "Item was NOT added to the shopping list.",
    }
    success_result = {
        "success": True,
        "verified": True,
        "product_id": "931316",
        "list_id": "list-uuid-1",
        "quantity": 1,
        "message": "Added 1x product 931316 to shopping list (verified)",
    }

    mock_search_result = {
        "products": [{"product_id": "931316", "name": "Milk"}],
    }

    with (
        patch("texas_grocery_mcp.tools.shopping_list.is_authenticated", return_value=True),
        patch(
            "texas_grocery_mcp.tools.shopping_list.shopping_list_add",
            new=AsyncMock(side_effect=[not_verified_result, success_result]),
        ),
        patch(
            "texas_grocery_mcp.tools.store.get_default_store_id",
            return_value="store-123",
        ),
        patch(
            "texas_grocery_mcp.tools.product.product_search",
            new=AsyncMock(return_value=mock_search_result),
        ),
    ):
        result = await shopping_list_add_with_retry(
            product_id="wrong-id", confirm=True, auto_correct_id=True
        )

    assert result["success"] is True
    assert result["auto_corrected"] is True
    assert result["original_product_id"] == "wrong-id"
    assert result["corrected_product_id"] == "931316"


# ---------------------------------------------------------------------------
# list_name routing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_shopping_list_get_returns_error_for_unknown_list_name():
    """shopping_list_get should return LIST_NOT_FOUND when the named list doesn't exist."""
    from texas_grocery_mcp.tools.shopping_list import shopping_list_get

    mock_client = AsyncMock()
    mock_client.get_shopping_lists = AsyncMock(return_value=MOCK_LISTS_RESPONSE)

    with (
        patch("texas_grocery_mcp.tools.shopping_list.is_authenticated", return_value=True),
        patch("texas_grocery_mcp.tools.shopping_list._get_client", return_value=mock_client),
        patch(
            "texas_grocery_mcp.tools.shopping_list.StateManager.get_default_shopping_list_name",
            return_value=None,
        ),
    ):
        result = await shopping_list_get(list_name="Does Not Exist")

    assert result.get("error") is True
    assert result["code"] == "LIST_NOT_FOUND"
    assert "Does Not Exist" in result["message"]


# ---------------------------------------------------------------------------
# shopping_list_check_auth
# ---------------------------------------------------------------------------

def test_shopping_list_check_auth_returns_status():
    """shopping_list_check_auth should return auth status dict."""
    from texas_grocery_mcp.tools.shopping_list import shopping_list_check_auth

    with patch("texas_grocery_mcp.auth.session.is_authenticated", return_value=False):
        result = shopping_list_check_auth()

    assert "authenticated" in result
    assert isinstance(result["authenticated"], bool)
