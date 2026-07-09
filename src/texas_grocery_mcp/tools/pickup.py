"""Pickup-timeslot MCP tools."""

from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field

from texas_grocery_mcp.auth.session import ensure_session, get_auth_instructions, is_authenticated
from texas_grocery_mcp.tools.store import get_default_store_id, set_default_store_id

if TYPE_CHECKING:
    from texas_grocery_mcp.clients.graphql import HEBGraphQLClient


def _get_client() -> "HEBGraphQLClient":
    """Get or create GraphQL client."""
    from texas_grocery_mcp.state import StateManager

    return StateManager.get_graphql_client_sync()


@ensure_session
async def pickup_times_get(
    store_id: Annotated[
        str | None,
        Field(description="Store ID to inspect. Defaults to the selected/default store."),
    ] = None,
) -> dict[str, Any]:
    """List available pickup windows for a store."""
    effective_store_id = (store_id or get_default_store_id() or "").strip()
    if not effective_store_id:
        return {
            "error": True,
            "code": "NO_STORE_SELECTED",
            "message": "No store selected. Use store_change first or pass a store_id.",
        }

    client = _get_client()
    try:
        result = await client.list_pickup_timeslots(effective_store_id)
        result.setdefault("message", f"Found pickup availability for store {effective_store_id}")
        return result
    except Exception as e:
        return {
            "error": True,
            "code": "PICKUP_TIMES_FETCH_FAILED",
            "message": f"Failed to fetch pickup times: {e!s}",
            "store_id": effective_store_id,
        }


@ensure_session
async def pickup_slot_reserve(
    slot_id: Annotated[
        str,
        Field(description="Timeslot ID returned by pickup_times_get", min_length=1),
    ],
    date: Annotated[str, Field(description="Pickup date in YYYY-MM-DD format")],
    store_id: Annotated[
        str | None,
        Field(description="Store ID for the reservation. Defaults to the selected/default store."),
    ] = None,
    confirm: Annotated[
        bool,
        Field(description="Set to true to confirm the pickup-timeslot reservation."),
    ] = False,
    ignore_conflicts: Annotated[
        bool,
        Field(description="Force reservation even if HEB reports cart conflicts."),
    ] = False,
) -> dict[str, Any]:
    """Reserve a pickup window, with confirmation and verification."""
    effective_store_id = (store_id or get_default_store_id() or "").strip()
    if not effective_store_id:
        return {
            "error": True,
            "code": "NO_STORE_SELECTED",
            "message": "No store selected. Use store_change first or pass a store_id.",
        }

    if not confirm:
        return {
            "preview": True,
            "action": "reserve_pickup_timeslot",
            "slot_id": slot_id,
            "date": date,
            "store_id": effective_store_id,
            "ignore_conflicts": ignore_conflicts,
            "message": "Set confirm=true to reserve this pickup timeslot.",
        }

    if not is_authenticated():
        return {
            "auth_required": True,
            "message": "Login required to reserve a pickup timeslot",
            "instructions": get_auth_instructions(),
        }

    client = _get_client()
    try:
        result = await client.reserve_timeslot(
            slot_id=slot_id,
            date=date,
            store_id=effective_store_id,
            ignore_conflicts=ignore_conflicts,
        )
        if result.get("success"):
            set_default_store_id(str(result.get("store_id") or effective_store_id))
            result.setdefault("message", "Pickup timeslot reserved and verified.")
        return result
    except Exception as e:
        return {
            "error": True,
            "code": "PICKUP_SLOT_RESERVE_FAILED",
            "message": f"Failed to reserve pickup timeslot: {e!s}",
            "slot_id": slot_id,
            "date": date,
            "store_id": effective_store_id,
        }
