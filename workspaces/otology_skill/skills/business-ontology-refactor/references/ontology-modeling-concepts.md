# 业务本体 核心概念参考

## 核心组成

| Ontology 概念 | Python 映射 | 说明 |
|--------------|-------------|------|
| **Entity Type** | `@dataclass class` | 业务实体，有唯一 全局标识 |
| **Property** | 类字段（`field: type`） | 实体的属性 |
| **Relationship** | 外键字段 + 导航属性 | 实体间关联，有方向和基数 |
| **Operation** | 实例方法 / classmethod | 对 实体的操作，可修改状态 |
| **Entity Set** | `list[XxxEntity]` | 同类型 实体的集合，可过滤 |

## 全局标识（Resource Identifier）

- 业务本体 平台上每个实体有全局唯一 全局标识
- 格式：`biz.<domain>.<entity>.<uuid>`
- Python 中统一用 `rid: str` 表示

## Relationship 基数

| 基数 | Python 表达 |
|------|------------|
| one-to-one | `other_rid: str` + `other: Optional[OtherClass]` |
| many-to-one | `parent_rid: str` + `parent: Optional[ParentClass]` |
| one-to-many | `children: list[ChildClass]` |
| many-to-many | `other_rids: list[str]` + `others: list[OtherClass]` |

## Operation 分类

| 类型 | 特征 | Python 映射 |
|------|------|-------------|
| 单对象 Operation | 操作单个 Entity | 实例方法 |
| 批量 Operation | 操作多个 Entity | `@classmethod` |
| 创建 Operation | 新建 Entity | `@classmethod` 返回新实例 |
| 关联 Operation | 修改 Relationship | 实例方法，修改 `_rid` 字段 |

## 常用 Property 类型

```python
# 基础类型
rid: str                    # 全局标识 主键
name: str                   # 名称
status: SomeEnum            # 枚举状态
created_at: datetime        # 创建时间
updated_at: datetime        # 更新时间
is_active: bool             # 布尔标志

# 数值类型
amount: float               # 金额
quantity: int               # 数量
score: float                # 评分/分数

# 关联类型（外键）
parent_rid: str             # 一对多外键
owner_rid: str              # 所有权外键
```

## 分析场景中的 Entity Set 操作

```python
# 业务本体 中 Entity Set 类似于 SQL 的 WHERE + 聚合
# Python 中等价于 list comprehension / filter

orders: list[Order] = [...]

# Filter（等价于 Entity Set filter）
pending_orders = [o for o in orders if o.status == OrderStatus.PENDING]

# Aggregate（等价于 Entity Set aggregate）
total_revenue = sum(o.total_amount for o in orders)
avg_order_value = total_revenue / len(orders) if orders else 0

# Group by
from collections import defaultdict
by_customer: dict[str, list[Order]] = defaultdict(list)
for o in orders:
    by_customer[o.customer_rid].append(o)
```
