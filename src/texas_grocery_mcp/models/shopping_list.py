"""Shopping list data models."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ShoppingListStore(BaseModel):
    """Store associated with a shopping list."""

    model_config = ConfigDict(populate_by_name=True)

    store_number: int = Field(alias="storeNumber")
    name: str


class ShoppingListFulfillment(BaseModel):
    """Fulfillment details for a shopping list."""

    store: ShoppingListStore


class ShoppingListPreview(BaseModel):
    """Preview of a shopping list as returned by getShoppingListsV2 (no item details)."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    total_item_count: int = Field(alias="totalItemCount")
    created: datetime
    updated: datetime
    is_active: bool = Field(alias="isActive")
    fulfillment: ShoppingListFulfillment | None = None


class GetShoppingListsV2Response(BaseModel):
    """Response from the getShoppingListsV2 query (list metadata only, no items)."""

    model_config = ConfigDict(populate_by_name=True)

    lists: list[ShoppingListPreview]


# ---------------------------------------------------------------------------
# getShoppingListV2 — single list with full item details
# ---------------------------------------------------------------------------

class ShoppingListItemPrice(BaseModel):
    """Price information for a shopping list item."""

    model_config = ConfigDict(populate_by_name=True)

    total_amount: float = Field(alias="totalAmount")
    list_price: float = Field(alias="listPrice")
    sale_price: float = Field(alias="salePrice")
    on_sale: bool = Field(alias="onSale")


class ShoppingListItemProduct(BaseModel):
    """Product details embedded in a shopping list item."""

    model_config = ConfigDict(populate_by_name=True)

    id: str  # productId (short numeric ID)
    full_display_name: str = Field(alias="fullDisplayName")


class ShoppingListItem(BaseModel):
    """An individual item on a shopping list as returned by getShoppingListV2."""

    model_config = ConfigDict(populate_by_name=True)

    id: str  # list-item UUID — required for deleteShoppingListItems
    product: ShoppingListItemProduct
    quantity: int
    item_price: ShoppingListItemPrice = Field(alias="itemPrice")
    group_header: str | None = Field(alias="groupHeader", default=None)


class ShoppingListItemPage(BaseModel):
    """Paginated container of shopping list items."""

    model_config = ConfigDict(populate_by_name=True)

    items: list[ShoppingListItem]


class GetShoppingListV2Response(BaseModel):
    """Response from the getShoppingListV2 query (single list with full item details)."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    item_page: ShoppingListItemPage = Field(alias="itemPage")
