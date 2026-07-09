"""Tests for pickup-time tools."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_pickup_times_get_uses_default_store_when_not_provided():
    """pickup_times_get should use the configured default store."""
    from texas_grocery_mcp.tools.pickup import pickup_times_get

    mock_client = MagicMock()
    mock_client.list_pickup_timeslots = AsyncMock(
        return_value={
            "store_id": "639",
            "days": [{"date": "2026-05-27", "slot_count": 1, "groups": []}],
            "available_days": 1,
            "display_messages": [],
        }
    )

    with (
        patch("texas_grocery_mcp.tools.pickup.get_default_store_id", return_value="639"),
        patch("texas_grocery_mcp.tools.pickup._get_client", return_value=mock_client),
    ):
        result = await pickup_times_get()

    mock_client.list_pickup_timeslots.assert_called_once_with("639")
    assert result["store_id"] == "639"
    assert result["available_days"] == 1


@pytest.mark.asyncio
async def test_pickup_times_get_requires_store_context():
    """pickup_times_get should fail clearly when no store is available."""
    from texas_grocery_mcp.tools.pickup import pickup_times_get

    with patch("texas_grocery_mcp.tools.pickup.get_default_store_id", return_value=None):
        result = await pickup_times_get()

    assert result["error"] is True
    assert result["code"] == "NO_STORE_SELECTED"


@pytest.mark.asyncio
async def test_pickup_slot_reserve_without_confirm_returns_preview():
    """pickup_slot_reserve should require confirm before changing state."""
    from texas_grocery_mcp.tools.pickup import pickup_slot_reserve

    result = await pickup_slot_reserve(slot_id="slot-123", date="2026-05-27", store_id="639")

    assert result["preview"] is True
    assert result["action"] == "reserve_pickup_timeslot"
    assert "confirm" in result["message"].lower()


@pytest.mark.asyncio
async def test_pickup_slot_reserve_requires_auth_when_confirmed():
    """pickup_slot_reserve should require authentication for reservation."""
    from texas_grocery_mcp.tools.pickup import pickup_slot_reserve

    with patch("texas_grocery_mcp.tools.pickup.is_authenticated", return_value=False):
        result = await pickup_slot_reserve(
            slot_id="slot-123",
            date="2026-05-27",
            store_id="639",
            confirm=True,
        )

    assert result["auth_required"] is True
    assert "instructions" in result


@pytest.mark.asyncio
async def test_pickup_slot_reserve_calls_client_and_returns_verified_result():
    """pickup_slot_reserve should return verified reservation details from the client."""
    from texas_grocery_mcp.tools.pickup import pickup_slot_reserve

    mock_client = MagicMock()
    mock_client.reserve_timeslot = AsyncMock(
        return_value={
            "success": True,
            "verified": True,
            "store_id": "639",
            "timeslot": {
                "id": "slot-123",
                "date": "2026-05-27",
                "start_time": "2026-05-27T08:00:00-05:00",
                "end_time": "2026-05-27T08:30:00-05:00",
                "expiry": "2026-05-25T09:39:37-05:00",
            },
        }
    )

    with (
        patch("texas_grocery_mcp.tools.pickup.is_authenticated", return_value=True),
        patch("texas_grocery_mcp.tools.pickup._get_client", return_value=mock_client),
        patch("texas_grocery_mcp.tools.pickup.set_default_store_id") as mock_set_default_store,
    ):
        result = await pickup_slot_reserve(
            slot_id="slot-123",
            date="2026-05-27",
            store_id="639",
            confirm=True,
        )

    mock_client.reserve_timeslot.assert_called_once_with(
        slot_id="slot-123",
        date="2026-05-27",
        store_id="639",
        ignore_conflicts=False,
    )
    mock_set_default_store.assert_called_once_with("639")
    assert result["success"] is True
    assert result["verified"] is True
    assert result["timeslot"]["id"] == "slot-123"
