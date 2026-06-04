# SQLAlchemy ORM Template

## base.py

```python
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass
```

---

## Single Table (No Relationships)

```python
from sqlalchemy import Column, Integer, String, Float, Boolean, Date, DateTime, Text
from sqlalchemy import UniqueConstraint
from models.base import Base
import datetime

class Product(Base):
    """Catalog entry for a sellable item, including pricing and availability status."""

    __tablename__ = "product"

    id = Column(Integer, primary_key=True, autoincrement=True,
                comment="Auto-incremented surrogate primary key")
    product_code = Column(String(50), nullable=False, unique=True,
                          comment="Unique business identifier code for the product (SKU)")
    product_name = Column(String(200), nullable=False,
                          comment="Full display name of the product shown to customers")
    category = Column(String(100), nullable=True,
                      comment="Broad classification grouping the product belongs to")
    price = Column(Float, nullable=False,
                   comment="Retail unit price in the system's base currency")
    is_active = Column(Boolean, default=True,
                       comment="Whether the product is currently available for sale")
    created_at = Column(DateTime, default=datetime.datetime.utcnow,
                        comment="Timestamp when the record was first inserted")

    def __repr__(self):
        return f"<Product(id={self.id}, product_code='{self.product_code}')>"
```

---

## Table With Foreign Key (Many-to-One)

```python
from sqlalchemy import Column, Integer, String, ForeignKey, Date
from sqlalchemy.orm import relationship
from models.base import Base

class Order(Base):
    """Header record for a customer purchase order, linked to the placing user."""

    __tablename__ = "order"

    id = Column(Integer, primary_key=True, autoincrement=True,
                comment="Auto-incremented surrogate primary key")
    order_no = Column(String(50), nullable=False, unique=True,
                      comment="Human-readable business order number (e.g., ORD-20240101-001)")

    # FK to User
    user_id = Column(Integer, ForeignKey("user.id"), nullable=False,
                     comment="Identifier of the user who placed this order — FK → User.id")
    user = relationship("User", back_populates="orders")

    order_date = Column(Date, nullable=False,
                        comment="Calendar date on which the order was placed")

    def __repr__(self):
        return f"<Order(id={self.id}, order_no='{self.order_no}')>"
```

The **parent** table (User) must also declare the reverse relationship:
```python
# In user.py
orders = relationship("Order", back_populates="user")
```

---

## Table With Multiple FKs

```python
from sqlalchemy import Column, Integer, String, Float, ForeignKey
from sqlalchemy.orm import relationship
from models.base import Base

class OrderItem(Base):
    """Individual line item within an order, capturing product, quantity, and price at time of purchase."""

    __tablename__ = "order_item"

    id = Column(Integer, primary_key=True, autoincrement=True,
                comment="Auto-incremented surrogate primary key")
    order_id = Column(Integer, ForeignKey("order.id"), nullable=False,
                      comment="Order this line item belongs to — FK → Order.id")
    product_id = Column(Integer, ForeignKey("product.id"), nullable=False,
                        comment="Product being purchased in this line — FK → Product.id")
    quantity = Column(Integer, nullable=False, default=1,
                      comment="Number of units of the product ordered")
    unit_price = Column(Float, nullable=False,
                        comment="Price per unit at the time the order was placed (may differ from current catalog price)")

    order = relationship("Order", back_populates="items")
    product = relationship("Product", back_populates="order_items")
```

---

## Many-to-Many (Association Table)

```python
from sqlalchemy import Table, Column, Integer, ForeignKey
from models.base import Base

# Association table (no class needed unless it has extra columns)
user_role = Table(
    "user_role",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("user.id"), primary_key=True),
    Column("role_id", Integer, ForeignKey("role.id"), primary_key=True),
)

# In User class:
roles = relationship("Role", secondary=user_role, back_populates="users")

# In Role class:
users = relationship("User", secondary=user_role, back_populates="roles")
```

---

## models/__init__.py Template

Import in **dependency order** (parents before children):

```python
# models/__init__.py
from models.base import Base

# Level 0 — no FK dependencies
from models.user import User
from models.product import Product
from models.region import Region

# Level 1 — depends on Level 0
from models.order import Order
from models.inventory import Inventory

# Level 2 — depends on Level 1
from models.order_item import OrderItem

__all__ = [
    "Base",
    "User", "Product", "Region",
    "Order", "Inventory",
    "OrderItem",
]
```

---

## Nullable / Default Rules

| Constraint in metadata | SQLAlchemy |
|-----------------------|------------|
| NOT NULL / 非空 | `nullable=False` |
| NULL / 可空 | `nullable=True` (default) |
| DEFAULT value | `default=value` or `server_default=text("value")` |
| UNIQUE | `unique=True` or `UniqueConstraint` |
| PRIMARY KEY | `primary_key=True` |
| AUTO_INCREMENT | `autoincrement=True` |
