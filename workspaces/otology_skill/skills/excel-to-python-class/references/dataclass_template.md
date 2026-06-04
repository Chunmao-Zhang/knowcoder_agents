# Dataclass Template

Use when the user wants pure Python dataclasses (no ORM dependency).

---

## Single Table

```python
from dataclasses import dataclass, field
from typing import Optional
import datetime

@dataclass
class Product:
    """Catalog entry for a sellable item, including pricing and availability status."""

    id: int                        # Auto-incremented surrogate primary key
    product_code: str              # Unique business identifier code for the product (SKU) — NOT NULL, UNIQUE
    product_name: str              # Full display name of the product shown to customers — NOT NULL
    category: Optional[str]        # Broad classification grouping the product belongs to
    price: float                   # Retail unit price in the system's base currency — NOT NULL
    is_active: bool = True         # Whether the product is currently available for sale
    created_at: datetime.datetime = field(
        default_factory=datetime.datetime.utcnow
    )                              # Timestamp when the record was first inserted
```

---

## Table With Foreign Key Reference

```python
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from models.user import User

@dataclass
class Order:
    """Header record for a customer purchase order, linked to the placing user."""

    id: int                           # Auto-incremented surrogate primary key
    order_no: str                     # Human-readable business order number — NOT NULL, UNIQUE
    user_id: int                      # Identifier of the user who placed this order — FK → User.id
    order_date: datetime.date         # Calendar date on which the order was placed — NOT NULL

    # Resolved relationship (not persisted, populated at runtime)
    user: Optional["User"] = field(default=None, repr=False)
    # FK relationship: Order (many) → User (one)
```

---

## Multiple FK References

```python
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from models.order import Order
    from models.product import Product

@dataclass
class OrderItem:
    """Individual line item within an order, capturing product, quantity, and price at time of purchase."""

    id: int                           # Auto-incremented surrogate primary key
    order_id: int                     # Order this line item belongs to — FK → Order.id
    product_id: int                   # Product being purchased in this line — FK → Product.id
    quantity: int                     # Number of units of the product ordered
    unit_price: float                 # Price per unit at the time the order was placed

    order: Optional["Order"] = field(default=None, repr=False)
    product: Optional["Product"] = field(default=None, repr=False)
```

---

## Relationships Summary Comment Block

Add this at the top of each file with relationships:

```python
# =============================================================
# RELATIONSHIPS DETECTED FOR OrderItem
# =============================================================
# order_id  → Order.id     (many-to-one, confidence: high)
# product_id → Product.id  (many-to-one, confidence: high)
# Potential join key: order_date (shared with Order, same type)
# =============================================================
```
