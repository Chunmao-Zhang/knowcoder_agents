---
name: business-ontology-refactor
description: >
  根据用户提出的分析问题以及提供的 Python class 定义，结合 业务本体建模规范
  及其四大设计原则（领域驱动、DRY、开放/闭合、PECS），对这些类进行针对性重构，
  使分析过程更加简单直接。具体包括：
  1. 识别哪些类、哪些成员变量与问题相关；
  2. 将 Entity Type 映射为 Python class，Operation 映射为类方法，Interface 映射为 Protocol；
  3. 提炼共性为 Interface，避免重复；
  4. 保留并明确表达表间外键关联（_rid 后缀）；
  5. 输出结构清晰、语义明确的重构代码及说明。
  当用户提到"业务本体"、"本体"、"Ontology"、"Entity Type"、"Operation"、"Interface"、
  "重构 class"、"分析封装"、"Python 类重构"时，必须使用此 skill。
---

# Business Ontology Class Refactor Skill

根据用户的**分析问题**和**现有 Python class 定义**，结合业务本体建模规范及四大设计原则，输出专为该问题优化的重构类代码。

## Tool Boundary

本 skill 负责业务理解、实体边界判断、接口抽象、字段筛选和最终说明；工具负责可重复的解析、写入和验证。执行时必须遵守以下边界：

- 如果输入来自前端上传 case，直接使用 prompt 中给出的 `prepared_models`、`generated_files` 和 `output_dir`，不要要求用户重复提供路径。
- 在设计业务本体前，必须调用 `parse_ontology_files` 解析相关 prepared Python class。可以先根据 case 摘要选择相关文件，但不能只用 `read_file` 手工浏览来替代解析工具。
- 禁止先批量 `read_file` prepared model 后直接手写业务本体；prepared class 的结构化解析必须由 `parse_ontology_files` 完成。如果没有完成这一步，本 skill 不能进入设计和写文件阶段。
- `read_file` 只用于补充查看少量源代码、确认字段注释或阅读 skill/reference；它不是 schema 解析步骤。
- 只有字段口径、样例值或 Excel 原始行对设计有决定性影响时，才补充调用 `inspect_excel_schema`。前端 case 已经完成基础 inspect/generate，不要默认重新检查所有 Excel。
- 输出 Python 文件后，必须调用 `validate_python_artifacts`。如果验证失败，先修改文件并再次验证，直到通过或明确说明无法通过的原因。
- 新产物必须写入仓库根目录下的 `outputs/otology_skill/cases/<case_id>/business_ontology/`。不要写入 `/workspaces/otology_skill/outputs/...`，不要在最终回答中给出这种路径。
- 最终回答末尾必须包含标准 `PROCESS_TRACE_JSON` fenced JSON block；这是给前端画过程图的机器数据，正文仍然用自然语言说明。
- 生成的 Python 文件中必须保留同名 `PROCESS_TRACE_JSON` 常量，便于前端在最终回答缺失时从 artifact 还原过程图。

Do not move the mandatory user-confirmation step into a tool; confirmation and
business-scope decisions remain part of this skill.

---

## 整体流程

```
0. 应用四大设计原则  → 贯穿全程的设计指导思想
1. 理解问题          → 明确分析目标、输出范围、粒度风险
2. 解析输入类        → 必须使用 parse_ontology_files 读取 prepared model 文件
3. 审查输入类        → 扫描字段、关联、方法；识别重复、共性和粒度差异
4. 映射 Ontology     → Entity Type→class，Operation→method，Interface→Protocol，Relationship→关联属性
5. 筛选相关字段      → 只保留对问题有帮助的成员变量，并说明删除/保留原因
6. 写入和验证        → 写入 business_ontology/，调用 validate_python_artifacts，失败先修正
7. 输出 trace        → Python 文件和最终回答末尾都保留 PROCESS_TRACE_JSON
```

**⚠️ 重要：Step 1 默认是强制性的交互步骤，必须完成以下流程才能进入 Step 2：**
1. 评估用户问题的完整性（检查 6 个维度）
2. 如果有维度缺失或问题过于单一，使用策略 A 或策略 B 进行澄清/扩展
3. 输出问题理解确认（包含所有 6 个维度和扩展场景）
4. 等待用户明确确认后，才能继续后续步骤

**例外：前端上传 Excel case 且用户已经给出明确问题时，不要阻塞式等待确认。** 这类请求应直接基于上传的 schema、prepared classes 和用户问题生成一个保守的第一版业务本体；缺失信息只在用户可读正文里简短说明，不要额外生成“口径提示/冲突提示”章节。只有当缺失信息会导致无法安全生成任何实体/关系时，才提出澄清问题。

前端 case 下的最小合规执行记录应能看出：`parse_ontology_files` → 写入 Python 文件 → `validate_python_artifacts` → 最终回答中的 `PROCESS_TRACE_JSON`。如果缺少其中任何一步，视为流程未完成；此时不要声称产物已完成，只能说明哪些步骤未完成以及需要如何重跑。

最终回答和 `PROCESS_TRACE_JSON` 不要求输出 `keep_separate`、`conflicts` 或“口径提示”。不要单独写“口径提示”“容易混淆的指标”“冲突清单”章节。

---

## 第零步：业务本体设计四项原则

> **这四条原则贯穿全部重构过程，每一个设计决策都应对照检查。**
> 以下四项原则用于指导稳定、可扩展、语义清晰的业务本体建模。

---

### 原则一：领域驱动设计（Domain-Driven Design）

> 现实世界的对象实体应**一对一**映射到数字孪生中，捕获数据的**语义**，而非只是结构。
> 目标：让业务用户和智能体都能"读懂"类定义，不需要额外解释。

**重构时的体现：**
- 类名必须对应真实业务实体（❌ `DataRecord` → ✅ `MaintenanceWorkOrder`）
- 字段语义清晰，避免泛化命名（❌ `value: float` → ✅ `contract_amount: float`）
- 枚举值用业务术语，不用数字码（❌ `status: int = 2` → ✅ `status: OrderStatus.APPROVED`）
- 关系要有业务含义，不只是技术外键

```python
# ❌ 技术化命名，语义丢失，智能体无法理解业务
class Record:
    id: str
    type: int
    val1: float
    val2: str

# ✅ 领域驱动，语义清晰，对应现实中纸质工单的数字孪生
class MaintenanceWorkOrder:
    """
    设备维保工单
    Ontology Entity: MaintenanceWorkOrder
    """
    rid: str
    asset_rid: str               # 关联被维保的资产（语义明确）
    priority: WorkOrderPriority  # 业务枚举，非数字
    scheduled_date: datetime
    estimated_cost: float
```

---

### 原则二：不要重复自己（DRY — Don't Repeat Yourself）

> 如果多个 Entity Type 有共性字段或流程，提炼为 **Interface（接口）**，发掘差异化特征。
> 这让人和智能体都能驾驭本体，识别主要表征和主要流程。

**重构时识别重复的信号：**
- 多个类有相同字段名且语义相同 → 提炼 Interface
- 多个类有相同方法签名 → 提炼 Interface 或 Mixin
- 重构时若发现在"重复做同一件事"，立刻停下来抽象

**Python 中用 `Protocol` 表达 Ontology Interface：**

```python
from typing import Protocol, runtime_checkable

# Interface：可审批的实体（多个 Entity Type 共用）
@runtime_checkable
class Approvable(Protocol):
    """Ontology Interface: Approvable"""
    rid: str
    status: str
    def approve(self, approver_rid: str) -> None: ...
    def reject(self, reason: str) -> None: ...

# Interface：绑定资产的实体
@runtime_checkable
class AssetBound(Protocol):
    """Ontology Interface: AssetBound"""
    asset_rid: str

# ✅ 多个 Entity Type 实现同一 Interface，避免重复定义审批逻辑
@dataclass
class PurchaseOrder:
    """implements: Approvable, AssetBound"""
    rid: str
    status: POStatus
    asset_rid: str
    amount: float
    def approve(self, approver_rid: str) -> None: ...
    def reject(self, reason: str) -> None: ...

@dataclass
class MaintenanceRequest:
    """implements: Approvable, AssetBound"""
    rid: str
    status: RequestStatus
    asset_rid: str
    def approve(self, approver_rid: str) -> None: ...
    def reject(self, reason: str) -> None: ...
```

**Interface 的额外能力：**
- 接口赋能工作流，可同时处理不同 Entity Type（如 Building 接口可同时建立参观、办公楼、体育馆）
- 本体支持**多重继承**：一个 Entity Type 可实现多个 Interface（如体育馆同时实现 `Building` 和 `BookableResource`）
- 接口本身也可分层，接口可以扩展出新接口（多层级接口）

```python
# 接口多层级示例
class Resource(Protocol):
    """顶层接口"""
    rid: str

class BookableResource(Resource, Protocol):
    """Resource 的子接口（接口扩展接口）"""
    def book(self, time_slot: datetime) -> "Booking": ...

class Building(Resource, Protocol):
    """Resource 的另一子接口"""
    address: str
    capacity: int

# 体育馆：多重继承自两个 Interface（本体模型支持多重继承）
@dataclass
class Stadium:
    """implements: Building, BookableResource（多重继承）"""
    rid: str
    address: str
    capacity: int
    sport_type: str
    def book(self, time_slot: datetime) -> "Booking": ...
```

---

### 原则三：开放/闭合原则（Open/Closed Principle）

> **核心数据模型对修改封闭**（稳定），**对扩展开放**（可组合新能力）。
> 基于稳定的核心，通过扩展适配统一接口，不破坏已有设计。
> 优先使用组合而非继承；接口通过多重继承来有效实现组合。

**重构决策：**
- 识别"核心稳定模型"（字段几乎不变）和"扩展模型"（随业务增长）
- 核心模型只包含最共性字段，不轻易打开修改
- 扩展模型**优先用组合**添加专属字段和方法（而非直接继承修改核心）
- 从市场安装的可扩展"类"对最终用户的修改是封闭的

```python
# ── 核心模型（对修改封闭，稳定） ────────────────────────────────────────────

@dataclass
class Asset:
    """
    Ontology Entity: Asset（核心，稳定，不轻易修改）
    Implements: Approvable
    """
    rid: str
    name: str
    asset_type: AssetType
    status: AssetStatus
    owner_rid: str

# ── 扩展模型（对扩展开放，通过组合引用核心） ─────────────────────────────────

@dataclass
class EquipmentAsset:
    """
    Ontology Entity: EquipmentAsset
    Extends Asset（通过组合，不修改 Asset 核心）
    Implements: AssetBound
    """
    asset: Asset                         # 组合引用核心，而非继承修改
    serial_number: str
    manufacturer: str
    next_maintenance_date: datetime

    # Equipment 专属 Operation
    def schedule_maintenance(self, date: datetime) -> "MaintenanceWorkOrder": ...

@dataclass
class SoftwareAsset:
    """Extends Asset（Software 专属扩展）"""
    asset: Asset
    license_key: str
    expiry_date: datetime
    seat_count: int
```

---

### 原则四：PECS — 生产者用 Extends，消费者用 Super（协变与逆变）

> **产出数据（生产者）用具体子类型**（协变 / Extends），**接收数据（消费者）用父接口类型**（逆变 / Super）。
> 等价于 Java 泛型的 `EntitySet<? extends T>` 和 `EntitySet<? super T>`。

**核心规则：**
- 方法**返回值**（生产者）：返回具体类型，调用方获得完整信息
- 方法**参数**（消费者）：接受接口/父类类型，提高复用性和灵活性

```python
from typing import TypeVar

T_Approvable = TypeVar("T_Approvable", bound=Approvable)

# ✅ 消费者（参数）用父接口 — 可接受任何 Approvable 对象（逆变）
# 等价建模形式: EntitySet<? super Approvable>
def bulk_approve(items: list[T_Approvable], approver_rid: str) -> list[T_Approvable]:
    """批量审批：接受任何实现 Approvable 的对象集合"""
    for item in items:
        item.approve(approver_rid)
    return items

# ✅ 安全调用：传入具体子类型（协变）
purchase_orders: list[PurchaseOrder] = [...]
maintenance_requests: list[MaintenanceRequest] = [...]

bulk_approve(purchase_orders, "approver_001")       # ✅ 安全，PurchaseOrder 实现了 Approvable
bulk_approve(maintenance_requests, "approver_001")  # ✅ 安全，MaintenanceRequest 也实现了 Approvable

# ✅ 生产者（返回值）用具体类型（协变）
# 等价建模形式: EntitySet<? extends MaintenanceWorkOrder>
def create_work_order(asset_rid: str) -> MaintenanceWorkOrder:
    ...  # 返回具体类型，不是 object 或 Any

# 实际场景：
# 读取 NBAGame 数据 → 安全传入 EntitySet<NBAGame>，因为 NBAGame extends Event
# 在 DevConKeynote 调用重排 → reschedule(DevConKeynote) 可安全调用 reschedule(? super Event)
```

---

## Step 1：理解分析问题（必须执行，不可跳过）

### 1.1 问题完整性评估（强制步骤）

**⚠️ 重要：在开始任何重构工作之前，必须先完成问题评估和澄清/扩展。**

首先评估用户提供的问题是否足够具体，逐项检查以下维度：

| 维度 | 要提取的内容 | 是否明确 | 如果不明确则必须澄清 |
|------|-------------|---------|---------------------|
| **核心实体** | 问题涉及哪些业务对象（如 Order、Employee、Asset） | ✓ / ✗ | 使用策略 A 询问 |
| **分析目标** | 聚合、预测、异常检测、关联分析…… | ✓ / ✗ | 使用策略 A 询问 |
| **关键指标** | 需要计算哪些值，依赖哪些字段 | ✓ / ✗ | 使用策略 A 询问 |
| **时间维度** | 是否涉及时序、历史、趋势 | ✓ / ✗ | 使用策略 B 扩展 |
| **关联路径** | 需要跨几张表 join | ✓ / ✗ | 使用策略 A 询问 |
| **业务场景** | 具体的使用场景和决策目标 | ✓ / ✗ | 使用策略 A 询问 |

**评估结果判断：**
- 如果有 **2 个或以上维度不明确** → 必须使用**策略 A（主动询问澄清）**
- 如果问题只涉及**单一时间维度或单一指标** → 必须使用**策略 B（问题扩展）**
- 如果所有维度都明确且已经是多维度问题 → 跳过澄清，直接进入 Step 1.3 问题确认

### 1.2 问题澄清与扩展策略

**当问题模糊或受限时，采用以下策略：**

#### 策略 A：主动询问澄清（核心策略，适用于关键信息缺失）

**识别缺失的关键维度，针对性提问。必须给出具体选项，避免开放式提问。**

```
示例 1：用户只说"分析订单数据"
→ 缺失：分析目标、关键指标、时间维度

澄清问题：
我需要了解更多细节来设计合适的类结构：

1. 您想分析订单的哪些方面？（可多选）
   a) 订单金额趋势（时序分析）
   b) 客户购买行为（关联分析）
   c) 异常订单检测（异常分析）
   d) 产品销售排名（聚合分析）
   e) 订单履约效率（流程分析）

2. 您关注的核心指标是什么？
   a) 订单总额、平均订单价值
   b) 订单数量、订单转化率
   c) 客户复购率、留存率
   d) 订单完成时长、延迟率
   e) 其他（请说明）

3. 时间范围和粒度？
   a) 实时监控（最近 24 小时）
   b) 短期趋势（按日/周，近 3 个月）
   c) 长期趋势（按月/季度，近 1-2 年）
   d) 同比/环比分析
   e) 不涉及时间维度

4. 这个分析用于什么决策？
   a) 运营优化（提升效率）
   b) 销售策略（促销、定价）
   c) 风控预警（异常检测）
   d) 高层汇报（KPI 监控）
   e) 其他（请说明）
```

```
示例 2：用户说"查看设备维保情况"
→ 缺失：具体分析目标、决策用途

澄清问题：
请帮我明确以下信息：

1. 您想了解维保的哪些信息？（可多选）
   a) 即将到期的维保计划（预警，未来 30/60/90 天）
   b) 维保成本分析（按设备类型/部门/时间段）
   c) 设备故障率与维保频次的关系（相关性分析）
   d) 维保工单完成率和及时率（运营效率）
   e) 维保供应商绩效评估
   f) 设备健康度评分（综合指标）

2. 涉及的设备范围？
   a) 所有设备
   b) 特定类型设备（请说明：如生产设备、IT 设备、车辆等）
   c) 特定部门/区域的设备
   d) 高价值/关键设备

3. 这个分析用于什么决策？
   a) 制定下季度维保预算
   b) 优化维保排期（减少停机时间）
   c) 评估设备更换 vs 持续维保的成本效益
   d) 考核维保团队/供应商
   e) 其他（请说明）

4. 需要关联哪些其他数据？
   a) 设备采购和资产信息
   b) 故障报修记录
   c) 备件库存
   d) 维保合同和供应商信息
   e) 不需要关联其他数据
```

```
示例 3：用户说"分析员工绩效"
→ 缺失：绩效维度、评估标准

澄清问题：
绩效分析涉及多个维度，请明确：

1. 您关注的绩效维度是？（可多选）
   a) 工作产出（任务完成量、质量）
   b) 工作效率（时长、响应速度）
   c) 团队协作（跨部门配合、知识分享）
   d) 创新贡献（提案数、采纳率）
   e) 客户满意度（投诉率、好评率）
   f) 其他（请说明）

2. 分析的时间范围？
   a) 月度绩效
   b) 季度绩效
   c) 年度绩效
   d) 绩效趋势对比（同比/环比）

3. 需要的对比维度？
   a) 员工个人纵向对比（历史表现）
   b) 员工横向对比（同岗位/同级别）
   c) 部门/团队对比
   d) 不需要对比

4. 分析结果用于？
   a) 绩效考核和奖金分配
   b) 晋升和调岗决策
   c) 培训需求识别
   d) 团队优化（人员配置）
   e) 其他（请说明）
```

**澄清提问的关键原则：**
- ✅ 必须给出具体选项（a/b/c/d），不要问"您想分析什么"这种开放式问题
- ✅ 选项要覆盖常见场景，但保留"其他"选项
- ✅ 问题要分层递进：先问"做什么"，再问"怎么做"，最后问"为什么"
- ✅ 每个问题都要说明缺失的维度（如"→ 缺失：分析目标"）
- ✅ 提供业务场景示例，帮助用户理解选项含义

#### 策略 B：基于问题扩展同类场景（重要策略，适用于问题过于单一或维度受限）

**当用户只提出一个具体问题时，主动扩展相关的同类业务问题，包括：**
- **时间维度扩展**：日 → 周 → 月 → 季度 → 年，同比/环比
- **空间维度扩展**：单点 → 区域 → 全局，部门 → 公司
- **指标维度扩展**：单一指标 → 多维度指标体系
- **分析深度扩展**：描述性 → 诊断性 → 预测性 → 决策性

```
示例 1：用户问"统计本月订单增长率"
→ 单一时间维度，可扩展为完整的增长分析体系

扩展建议：
您提到的"本月订单增长率"是一个很好的起点。为了让类设计更有价值，我建议扩展到：

【时间维度扩展】
✓ 本月订单增长率（您提出的）
+ 本周订单增长率（更短周期，快速响应）
+ 本季度订单增长率（中期趋势）
+ 本年度订单增长率（长期趋势）
+ 同比增长率（今年 4 月 vs 去年 4 月）
+ 环比增长率（4 月 vs 3 月）
+ 滚动 N 天增长率（如最近 7/30/90 天）

【指标维度扩展】
+ 订单数量增长率
+ 订单金额增长率
+ 客户数增长率（新增客户 vs 流失客户）
+ 平均订单价值增长率

【分析深度扩展】
+ 增长率趋势图（可视化）
+ 增长率异常检测（突然下降预警）
+ 增长率预测（基于历史数据预测下月）
+ 增长驱动因素分析（哪些产品/客户/渠道贡献了增长）

请确认您需要的范围：
a) 只需要本月订单增长率（单一指标）
b) 需要多时间维度的增长率对比（日/周/月/季/年）
c) 需要完整的增长分析体系（包含预测和归因）
```

```
示例 2：用户问"哪些客户的订单金额超过 10 万"
→ 简单过滤查询，可扩展为客户价值分析

扩展建议：
您的问题是筛选高价值客户。我建议扩展到更全面的客户分析：

【筛选条件扩展】
✓ 订单金额 > 10 万（您提出的）
+ 订单金额在不同区间的客户分层（<1万、1-5万、5-10万、>10万）
+ 时间范围：本月/本季度/本年度/历史累计
+ 客户类型：新客户 vs 老客户

【关联分析扩展】
+ 高价值客户的订单频次（购买几次达到 10 万）
+ 高价值客户的复购率和留存率
+ 高价值客户主要购买的产品类别
+ 高价值客户的订单状态分布（待审批/已完成/已取消）
+ 高价值客户的地域分布

【客户价值体系扩展】
+ RFM 分析（Recency 最近购买、Frequency 购买频次、Monetary 购买金额）
+ 客户生命周期价值（CLV）预测
+ 客户流失预警（曾经高价值但近期无订单）
+ 客户晋升路径（从低价值到高价值的转化）

请选择：
a) 只需要简单筛选（金额 > 10万）
b) 需要客户分层和对比分析
c) 需要完整的客户价值分析体系
```

```
示例 3：用户问"统计每个产品的销量"
→ 单一聚合查询，可扩展为产品分析体系

扩展建议：
基于"产品销量统计"，我建议扩展到：

【时间维度扩展】
✓ 当前产品销量（您提出的）
+ 产品销量趋势（按日/周/月/季度）
+ 产品销量同比/环比对比
+ 产品销售周期分析（淡季/旺季）

【空间维度扩展】
+ 产品在不同区域的销量分布
+ 产品在不同渠道的销量分布（线上/线下/经销商）
+ 产品在不同客户群体的销量分布（企业客户/个人客户）

【指标维度扩展】
+ 产品销量（数量）
+ 产品销售额（金额）
+ 产品销售额占比（贡献度）
+ 产品库存周转率（销量 / 库存）
+ 产品退货率
+ 产品毛利率

【分析深度扩展】
+ 产品销量排名（Top N / Bottom N）
+ 产品生命周期分析（新品/成长/成熟/衰退）
+ 产品关联销售分析（经常一起购买的产品）
+ 产品销量预测（基于历史趋势）
+ 产品滞销预警（销量持续下降）

请告诉我：
a) 只需要基础销量统计（单一时间点）
b) 需要多维度销量分析（时间/空间/指标）
c) 需要完整的产品分析能力（包含预测和优化建议）
```

```
示例 4：用户问"查看设备的维保记录"
→ 单一实体查询，可扩展为设备全生命周期管理

扩展建议：
"设备维保记录"是设备管理的一部分，建议扩展到：

【时间维度扩展】
✓ 历史维保记录（您提出的）
+ 即将到期的维保计划（未来 30/60/90 天）
+ 维保频次统计（按月/季度/年）
+ 维保周期分析（平均多久维保一次）

【关联数据扩展】
+ 设备基本信息（型号、采购日期、价值）
+ 设备故障记录（故障类型、频次、停机时长）
+ 设备备件更换记录
+ 维保成本记录（人工费、材料费）
+ 维保供应商信息

【分析维度扩展】
+ 设备健康度评分（综合维保、故障、使用年限）
+ 设备故障率与维保频次的相关性
+ 维保成本趋势（是否逐年上升）
+ 设备更换 vs 持续维保的成本效益分析
+ 维保及时率（计划维保 vs 实际维保的时间差）

【决策支持扩展】
+ 维保预算预测（下季度/下年度）
+ 设备更换建议（维保成本过高的设备）
+ 维保排期优化（减少停机时间）
+ 维保供应商绩效评估

请确认：
a) 只需要查看维保记录（历史数据）
b) 需要维保计划和预警功能
c) 需要完整的设备生命周期管理和决策支持
```

```
示例 5：用户问"员工本月的任务完成情况"
→ 单一时间维度的绩效查询，可扩展为绩效管理体系

扩展建议：
基于"本月任务完成情况"，建议扩展到：

【时间维度扩展】
✓ 本月任务完成情况（您提出的）
+ 本周任务完成情况（更高频的跟踪）
+ 本季度任务完成情况（中期绩效）
+ 本年度任务完成情况（年度考核）
+ 任务完成率趋势（逐月对比）
+ 同比/环比对比（今年 vs 去年）

【指标维度扩展】
+ 任务完成数量（完成了多少个任务）
+ 任务完成率（完成数 / 总任务数）
+ 任务完成质量（质量评分、返工率）
+ 任务完成及时率（按时完成 / 延期完成）
+ 任务平均耗时（效率指标）

【对比维度扩展】
+ 员工个人纵向对比（本月 vs 上月 vs 去年同期）
+ 员工横向对比（同岗位/同级别员工排名）
+ 部门/团队对比（团队平均水平）
+ 任务类型对比（不同类型任务的完成情况）

【分析深度扩展】
+ 任务完成瓶颈分析（哪些任务经常延期）
+ 员工工作负荷分析（任务数量是否合理）
+ 员工能力画像（擅长哪类任务）
+ 绩效预警（完成率持续下降的员工）
+ 绩效改进建议（培训需求识别）

请选择：
a) 只需要本月任务完成情况（单一时间点）
b) 需要多时间维度的绩效对比
c) 需要完整的绩效管理和分析体系
```

**问题扩展的关键原则：**
- ✅ **时间维度必扩展**：从单一时间点扩展到多时间维度（日/周/月/季/年）和对比（同比/环比）
- ✅ **空间维度要考虑**：从单点扩展到区域、部门、全局
- ✅ **指标维度要丰富**：从单一指标扩展到指标体系（数量、金额、占比、率）
- ✅ **分析深度要递进**：从描述性（是什么）→ 诊断性（为什么）→ 预测性（会怎样）→ 决策性（怎么办）
- ✅ **给出具体选项**：让用户选择 a/b/c，而不是开放式询问
- ✅ **保持克制**：扩展要合理，不要过度复杂化简单需求

### 1.3 问题确认输出（强制步骤）

**⚠️ 在完成澄清或扩展后，必须输出以下确认信息，并等待用户确认后才能继续 Step 2。**

输出格式：

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【问题理解确认】

核心实体：{列出涉及的业务对象}
分析目标：{明确的分析类型和目的}
关键指标：{需要计算的具体指标}
时间维度：{时间范围和粒度}
关联路径：{实体间的关联关系}
业务场景：{具体的使用场景和决策目标}

【扩展场景】（如果进行了问题扩展）
基于您的问题，我建议支持以下扩展分析：
1. {扩展场景 1}
2. {扩展场景 2}
3. {扩展场景 3}
...

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

请确认以上理解是否正确。如果确认无误，我将基于此进行类重构设计。
如果需要调整，请告诉我需要修改的部分。
```

**示例输出：**

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【问题理解确认】

核心实体：Order（订单）、Customer（客户）、Product（产品）
分析目标：客户价值分层与流失预警
关键指标：订单总额、订单频次、最近购买时间、客户生命周期价值（CLV）
时间维度：近 12 个月历史数据，按月聚合；支持同比/环比分析
关联路径：Customer → Order → OrderLine → Product
业务场景：制定客户留存策略，识别高风险流失客户，优化营销资源分配

【扩展场景】
基于您的"筛选高价值客户"问题，我建议支持以下扩展分析：
1. 客户 RFM 分层（Recency/Frequency/Monetary）
2. 客户复购率和留存率趋势
3. 客户流失预警（曾经高价值但近期无订单）
4. 客户晋升路径分析（从低价值到高价值的转化）
5. 客户产品偏好分析（主要购买的产品类别）

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

请确认以上理解是否正确。如果确认无误，我将基于此进行类重构设计。
如果需要调整，请告诉我需要修改的部分。
```

> **关键要求：**
> - 必须等待用户明确确认（如"确认"、"没问题"、"开始吧"）后，才能进入 Step 2
> - 如果用户提出修改意见，返回 Step 1.2 重新澄清或扩展
> - 不要在用户确认前就开始审查输入类或进行重构设计

---

## Step 2：审查输入的 Python Class

对每个 class 做如下扫描：

```
class XxxEntity:
    # 识别以下信息：
    # - 字段名 & 类型（哪些是 ID/外键/指标/枚举/时间戳）
    # - 现有方法（业务逻辑 / 数据获取 / 动作方法）
    # - 注释中是否有 @object_type / @action_type / @link_type 标注
    # - 与其他 class 的外键关联（命名模式：xxx_id / xxx_rid / fk_xxx）
    # - 跨类重复出现的字段 → 候选 Interface（DRY 原则）
    # - ⚠️ 继承关系识别（is-a 关系）→ 必须在重构中体现
```

### 2.1 识别继承关系（重要！）

**继承关系的识别信号：**

1. **字段包含关系**：子类包含父类的所有字段 + 额外专属字段
   ```python
   # 信号：Vehicle 的所有字段都出现在 Car 和 Truck 中
   class Vehicle:
       rid: str
       brand: str
       model: str
       year: int
   
   class Car:  # 包含 Vehicle 所有字段 + 专属字段
       rid: str
       brand: str      # ← 来自 Vehicle
       model: str      # ← 来自 Vehicle
       year: int       # ← 来自 Vehicle
       num_doors: int  # ← Car 专属
   
   # ✅ 识别为：Car extends Vehicle
   ```

2. **类名语义关系**：子类名是父类名的特化（is-a 关系）
   ```python
   # 信号：EquipmentAsset is-a Asset, SoftwareAsset is-a Asset
   class Asset: ...
   class EquipmentAsset: ...  # ✅ is-a Asset
   class SoftwareAsset: ...   # ✅ is-a Asset
   
   # 信号：Manager is-a Employee, Engineer is-a Employee
   class Employee: ...
   class Manager: ...         # ✅ is-a Employee
   class Engineer: ...        # ✅ is-a Employee
   ```

3. **注释或文档中的说明**：
   ```python
   class EquipmentAsset:
       """设备类资产，继承自 Asset"""  # ✅ 明确说明继承关系
       # 或者
       """Extends: Asset"""
   ```

4. **方法继承模式**：子类有父类的所有方法 + 额外方法
   ```python
   class Asset:
       def depreciate(self): ...
       def transfer_owner(self): ...
   
   class EquipmentAsset:
       def depreciate(self): ...      # ← 来自 Asset
       def transfer_owner(self): ...  # ← 来自 Asset
       def schedule_maintenance(self): ...  # ← EquipmentAsset 专属
   
   # ✅ 识别为：EquipmentAsset extends Asset
   ```

**⚠️ 重要：如果识别出继承关系，必须在重构代码中明确体现！**

建立**实体-字段-关联-继承**清单（内部使用），格式：

```
Entity: OrderLine
  fields:  order_id(FK→Order), product_id(FK→Product), quantity, unit_price, status
  links:   belongs_to Order, references Product
  actions: approve_order(), cancel_line()
  repeats: [status, approve()] 与 PurchaseOrder 重复 → 候选 Approvable Interface
  extends: None

Entity: EquipmentAsset
  fields:  rid, name, asset_type, status, owner_rid (来自 Asset), serial_number, manufacturer (专属)
  links:   owner_rid → User
  actions: depreciate(), transfer_owner() (来自 Asset), schedule_maintenance() (专属)
  repeats: None
  extends: Asset ← ⚠️ 继承关系，必须在重构中体现
```

---

## Step 3：业务本体 映射规则

### 3.1 Entity Type → Python Dataclass（支持继承）

**基础映射：**

```python
@dataclass
class Order:
    """
    Ontology Entity: Order
    Implements: Approvable          ← 实现的 Interface
    Primary Key: rid

    分析相关字段：total_amount, status, created_at
    已省略：shipping_address, internal_notes（与当前分析无关）

    Relationships:
      customer_rid → Customer (many-to-one)
      line_items   → OrderLine (one-to-many)
    """
    rid: str                    # 全局唯一标识，全局唯一标识
    order_number: str
    status: OrderStatus         # 枚举，非裸字符串（DDD 原则）
    created_at: datetime
    total_amount: float
    customer_rid: str           # FK → Customer
```

**⚠️ 继承映射（重要！）：**

当识别出继承关系时，必须使用 Python 类继承语法：

```python
# ── 父类（基类）────────────────────────────────────────────────────────────

@dataclass
class Asset:
    """
    Ontology Entity: Asset（基类）
    Primary Key: rid
    
    这是所有资产的基类，包含共性字段
    """
    rid: str
    name: str
    asset_type: str
    status: AssetStatus
    owner_rid: str
    purchase_date: datetime
    purchase_price: float
    
    # 共性方法（所有子类都继承）
    def depreciate(self, years: int) -> float:
        """Operation: DepreciateAsset"""
        ...
    
    def transfer_owner(self, new_owner_rid: str) -> "Asset":
        """Operation: TransferAssetOwner"""
        self.owner_rid = new_owner_rid
        return self


# ── 子类（继承自 Asset）───────────────────────────────────────────────────

@dataclass
class EquipmentAsset(Asset):  # ← ⚠️ 明确继承关系
    """
    Ontology Entity: EquipmentAsset
    Extends: Asset              ← 标注继承关系
    
    设备类资产，继承 Asset 的所有字段和方法，并添加设备专属字段
    """
    # 不需要重复定义 rid, name, asset_type 等父类字段
    # Python 继承会自动获得这些字段
    
    serial_number: str          # ← EquipmentAsset 专属字段
    manufacturer: str
    next_maintenance_date: datetime
    
    # EquipmentAsset 专属方法
    def schedule_maintenance(self, date: datetime) -> "MaintenanceWorkOrder":
        """Operation: ScheduleMaintenance（子类专属）"""
        ...


@dataclass
class SoftwareAsset(Asset):   # ← ⚠️ 明确继承关系
    """
    Ontology Entity: SoftwareAsset
    Extends: Asset
    
    软件类资产，继承 Asset 的所有字段和方法，并添加软件专属字段
    """
    license_key: str            # ← SoftwareAsset 专属字段
    expiry_date: datetime
    seat_count: int
    vendor: str
    
    # SoftwareAsset 专属方法
    def renew_license(self, new_expiry: datetime) -> "SoftwareAsset":
        """Operation: RenewSoftwareLicense（子类专属）"""
        ...


# ── 多层继承示例 ──────────────────────────────────────────────────────────

@dataclass
class Vehicle(Asset):         # ← Vehicle extends Asset
    """
    Ontology Entity: Vehicle
    Extends: Asset
    """
    vin: str                   # Vehicle Identification Number
    mileage: int
    fuel_type: str


@dataclass
class Car(Vehicle):           # ← Car extends Vehicle extends Asset（多层继承）
    """
    Ontology Entity: Car
    Extends: Vehicle
    
    继承链：Car → Vehicle → Asset
    """
    num_doors: int
    transmission_type: str


@dataclass
class Truck(Vehicle):         # ← Truck extends Vehicle extends Asset
    """
    Ontology Entity: Truck
    Extends: Vehicle
    """
    cargo_capacity: float
    num_axles: int
```

**继承 vs 组合的选择原则：**

| 场景 | 使用继承（extends） | 使用组合（has-a） |
|------|-------------------|------------------|
| **is-a 关系** | ✅ Car is-a Vehicle | ❌ |
| **字段完全包含** | ✅ 子类有父类所有字段 + 专属字段 | ❌ |
| **行为完全继承** | ✅ 子类有父类所有方法 + 专属方法 | ❌ |
| **核心稳定扩展** | ❌ 核心模型对修改封闭（O/C 原则） | ✅ 通过组合扩展 |
| **多重能力组合** | ❌ | ✅ 用 Interface 多重继承 |

```python
# ✅ 使用继承：明确的 is-a 关系
class Manager(Employee):  # Manager is-a Employee
    department: str
    team_size: int

# ✅ 使用组合：核心模型稳定封闭（O/C 原则）
class EquipmentAsset:
    asset: Asset          # 组合引用核心，不修改 Asset
    serial_number: str

# ✅ 使用 Interface 多重继承：多重能力组合
@dataclass
class Stadium:
    """implements: Building, BookableResource（多重 Interface）"""
    rid: str
    address: str          # from Building
    capacity: int         # from Building
    def book(self, time_slot: datetime) -> "Booking": ...  # from BookableResource
```

**⚠️ 重构输出要求：**
- 如果识别出继承关系，必须使用 `class Child(Parent):` 语法
- 子类不要重复定义父类已有的字段和方法
- 在 docstring 中明确标注 `Extends: ParentClass`
- 在关联关系图中标注继承关系（用 `→` 表示）

### 3.2 Interface → Python Protocol（DRY 原则）

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class Approvable(Protocol):
    """
    Ontology Interface: Approvable
    被 Order、PurchaseOrder、MaintenanceRequest 等实现
    """
    rid: str
    status: str
    def approve(self, approver_rid: str) -> None: ...
    def reject(self, reason: str) -> None: ...
```

### 3.3 Operation → Class Method

```python
@dataclass
class Order:
    # 单对象 Operation → 实例方法（生产者，返回具体类型）
    def approve(self, approver_rid: str) -> "Order":
        """Operation: ApproveOrder"""
        self.status = OrderStatus.APPROVED
        return self

    def cancel(self, reason: str) -> "Order":
        """Operation: CancelOrder"""
        self.status = OrderStatus.CANCELLED
        return self

    # 批量 Operation → classmethod（PECS：消费者参数用 Interface 类型）
    @classmethod
    def bulk_approve(cls, orders: "list[T_Approvable]", approver_rid: str) -> "list[T_Approvable]":
        """Operation: BulkApprove — 消费者接受 Approvable，不限具体类型"""
        for o in orders:
            o.approve(approver_rid)
        return orders
```

### 3.4 Relationship → 关联属性（外键 + 导航）

关联基数对照表：

| 基数 | 外键字段 | 导航属性 |
|------|---------|---------|
| many-to-one | `parent_rid: str` | `parent: Optional[Parent]` |
| one-to-many | 无 | `children: list[Child]` |
| many-to-many | `other_rids: list[str]` | `others: list[Other]` |

```python
@dataclass
class OrderLine:
    """
    Relationships:
      order_rid   → Order   (many-to-one)
      product_rid → Product (many-to-one)
    """
    rid: str
    order_rid: str              # FK → Order
    product_rid: str            # FK → Product
    quantity: int
    unit_price: float

    # 导航属性（repr=False 避免循环引用打印）
    order: Optional["Order"]     = field(default=None, repr=False)
    product: Optional["Product"] = field(default=None, repr=False)

    def line_total(self) -> float:
        return self.quantity * self.unit_price
```

---

## Step 4：字段筛选原则

| 保留 | 移除（在 docstring 中注明原因） |
|------|-------------------------------|
| 参与计算的指标字段 | 纯展示字段（display_name、icon_url） |
| 过滤/分组用的维度字段 | 与问题无关的配置字段 |
| 外键（维持关联路径） | 重复冗余字段（已可通过关联获取） |
| 时间戳（如有时序分析） | 内部系统字段（created_by_system 等） |
| 状态/枚举字段（驱动业务逻辑） | |

---

## Step 5：输出结构

### 5.1 输出顺序

1. **问题理解摘要**（1-3 句话，确认分析目标）
2. **Interface 设计**（提炼共性，说明哪些类实现哪些接口）
3. **相关类清单**（说明选取了哪些类，为什么）
4. **重构后的 Python 代码**（完整可运行，Interface → Enum → Entity Types 顺序）
5. **关联关系图**（文字版 ER 图）
6. **四原则应用说明**（解释每条原则如何体现在重构中）

前端最终回答必须使用项目统一章节标题：`## 产出总结`、`## 业务本体设计`、`## 输出文件`、`## 核心关系`、`## 验证结果与假设`。不要给这些标题加编号。章节后必须追加 `PROCESS_TRACE_JSON` fenced JSON block；这段是给前端读取过程图的机器数据，正文不要围绕 JSON 本身做解释。

`PROCESS_TRACE_JSON` 至少包含：

```json
{
  "workflow_steps": [
    {"step": "parse_prepared_classes", "tool": "parse_ontology_files", "status": "PASS", "evidence": ["outputs/otology_skill/cases/<case_id>/prepared_models/..."]},
    {"step": "write_business_ontology", "tool": "write_file", "status": "PASS", "evidence": ["outputs/otology_skill/cases/<case_id>/business_ontology/<file>.py"]},
    {"step": "validate_artifacts", "tool": "validate_python_artifacts", "status": "PASS", "evidence": ["outputs/otology_skill/cases/<case_id>/business_ontology/<file>.py"]}
  ],
  "source_to_target": [
    {
      "source_sheet": "原始 sheet 或文件名",
      "source_class": "prepared model class",
      "target_class": "业务实体 class",
      "decision": "rename|merge|split|reference|keep",
      "selected_fields": ["field_a"],
      "reason": "为什么这样映射"
    }
  ],
  "artifact_paths": ["outputs/otology_skill/cases/<case_id>/business_ontology/<file>.py"],
  "validation": {"py_compile": "PASS", "validate_python_artifacts": "PASS"}
}
```

### 5.2 完整代码模板

```python
"""
问题：{用户问题简述}
重构目标：{聚焦的分析维度}
涉及 Ontology：
  Entity Types: {列表}
  Operations: {列表}
  Interfaces:   {列表}

设计原则应用：
  [DDD]  类名/字段名对应真实业务实体
  [DRY]  {共性} 提炼为 Interface: {InterfaceName}
  [O/C]  {核心类} 稳定封闭，{扩展类} 通过组合扩展
  [PECS] bulk_xxx 参数用 Interface 类型（逆变），返回值用具体类型（协变）
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Protocol, TypeVar, runtime_checkable


# ── Interfaces（DRY 原则：提炼共性，避免重复） ─────────────────────────────────

@runtime_checkable
class Approvable(Protocol):
    """Ontology Interface: Approvable"""
    rid: str
    status: str
    def approve(self, approver_rid: str) -> None: ...
    def reject(self, reason: str) -> None: ...

T_Approvable = TypeVar("T_Approvable", bound=Approvable)


# ── 枚举类型（DDD 原则：业务术语，非数字码） ──────────────────────────────────

class OrderStatus(Enum):
    PENDING   = "pending"
    APPROVED  = "approved"
    CANCELLED = "cancelled"


# ── Entity Types ──────────────────────────────────────────────────────────────

@dataclass
class Order:
    """
    Ontology Entity: Order
    Implements: Approvable
    分析相关字段：total_amount, status, created_at
    已省略：shipping_address（与当前分析无关）

    Relationships:
      customer_rid → Customer (many-to-one)
      line_items   → OrderLine (one-to-many)
    """
    rid: str
    order_number: str
    status: OrderStatus
    created_at: datetime
    total_amount: float
    customer_rid: str                                         # FK → Customer

    line_items: list[OrderLine] = field(default_factory=list, repr=False)
    customer: Optional[Customer] = field(default=None, repr=False)

    # ── Operations ──────────────────────────────────────────────────────────

    def approve(self, approver_rid: str) -> Order:
        """Operation: ApproveOrder（生产者，返回具体类型 Order）"""
        self.status = OrderStatus.APPROVED
        return self

    def cancel(self, reason: str) -> Order:
        """Operation: CancelOrder"""
        self.status = OrderStatus.CANCELLED
        return self

    @classmethod
    def bulk_approve(cls, orders: list[T_Approvable], approver_rid: str) -> list[T_Approvable]:
        """Operation: BulkApprove（PECS 逆变：消费者接受 Approvable，不限具体类型）"""
        for o in orders:
            o.approve(approver_rid)
        return orders

    # ── 分析辅助方法 ──────────────────────────────────────────────────────────

    def line_count(self) -> int:
        return len(self.line_items)

    def total_quantity(self) -> int:
        return sum(li.quantity for li in self.line_items)

    def lines_in_period(self, start: datetime, end: datetime) -> list[OrderLine]:
        """时序分析辅助"""
        return [li for li in self.line_items if start <= li.created_at <= end]


@dataclass
class OrderLine:
    """
    Ontology Entity: OrderLine
    Relationships:
      order_rid   → Order   (many-to-one)
      product_rid → Product (many-to-one)
    """
    rid: str
    order_rid: str              # FK → Order
    product_rid: str            # FK → Product
    quantity: int
    unit_price: float

    order: Optional[Order]     = field(default=None, repr=False)
    product: Optional[Product] = field(default=None, repr=False)

    def line_total(self) -> float:
        return self.quantity * self.unit_price


# ── 分析视图类（非 核心业务实体，纯分析用）─────────────────────────────────

@dataclass
class CustomerOrderSummary:
    """分析视图：聚合结果，非 Ontology Entity"""
    customer_rid: str
    order_count: int
    total_spend: float
    avg_order_value: float
```

### 5.3 关联关系图（文字版）

```
[Interfaces]       [Entity Types]
Approvable ──── Order ──< OrderLine >── Product
                  │
                  └── Customer

[继承关系示例]
Asset (基类)
  ├─→ EquipmentAsset (子类)
  ├─→ SoftwareAsset (子类)
  └─→ Vehicle (子类)
        ├─→ Car (孙类)
        └─→ Truck (孙类)

[多重继承示例]
Building ──────┐
               ├── Stadium（多重 Interface 继承）
BookableResource ──┘

[完整示例：继承 + 关联 + Interface]
                    Approvable (Interface)
                         ↑
                         │ implements
                         │
Asset (基类) ────────→ Order ──< OrderLine >── Product
  ↑                      │
  │ extends              └── Customer
  │
  ├─→ EquipmentAsset ──< MaintenanceWorkOrder
  │        │
  │        └── Supplier (many-to-one)
  │
  └─→ SoftwareAsset
           │
           └── Vendor (many-to-one)

图例：
  ─→  继承关系 (extends)
  ──  关联关系 (has-a / references)
  ──< 一对多关联 (one-to-many)
  >── 多对一关联 (many-to-one)
  ↑   实现接口 (implements)
```

### 5.4 四原则应用说明（必须输出此节）

```
[DDD]  Order/OrderLine 命名对应真实业务实体；
       字段语义明确（estimated_cost 而非 val1；OrderStatus.APPROVED 而非 status=2）

[DRY]  approve/reject 在 Order 和 PurchaseOrder 中重复 → 提炼为 Approvable Interface；
       Stadium 同时需要 Building 和 BookableResource 能力 → 多重 Interface 继承

[O/C]  Asset 核心字段稳定封闭；
       EquipmentAsset 通过组合 Asset 扩展 Equipment 专属字段，不修改核心类

[PECS] bulk_approve(items: list[T_Approvable]) 消费者接受父接口类型（逆变）；
       create_work_order() -> MaintenanceWorkOrder 生产者返回具体类型（协变）
```

---

## 常见模式速查

### 多重继承（本体模型支持）

```python
# 体育馆：同时实现建筑物和可预约资源两个 Interface
@dataclass
class Stadium:
    """implements: Building, BookableResource（多重 Interface 继承）"""
    rid: str
    address: str        # from Building Interface
    capacity: int       # from Building Interface
    sport_type: str     # Stadium 专属
    def book(self, time_slot: datetime) -> "Booking": ...  # from BookableResource Interface
```

### 开放/闭合 — 组合优于直接继承

```python
# 优先用组合扩展，而非直接修改核心类字段
@dataclass
class EquipmentAsset:
    asset: Asset                    # 组合核心（封闭），绝不修改 Asset
    serial_number: str              # 扩展专属字段（开放）
    next_maintenance_date: datetime
    def schedule_maintenance(self, date: datetime) -> "MaintenanceWorkOrder": ...
```

### PECS — EntitySet 读写

```python
# 读取（生产者）→ 具体类型（协变）
nba_games: list[NBAGame] = fetch_games()

# 处理（消费者）→ 父接口类型（逆变），可安全传入任何子类型
def reschedule_events(events: list[T_Event], new_time: datetime) -> list[T_Event]:
    """接受 NBAGame、DevConKeynote 等任何 Event 子类型"""
    ...

reschedule_events(nba_games, new_time)        # ✅ NBAGame extends Event
reschedule_events(dev_keynotes, new_time)      # ✅ DevConKeynote extends Event
```

### 聚合分析 — 分析视图类

```python
# 当问题需要跨多个实体聚合时，引入分析视图类（非 核心业务实体）
@dataclass
class CustomerOrderSummary:
    """分析视图：非 Ontology Entity，仅用于当前分析"""
    customer_rid: str
    order_count: int
    total_spend: float
    avg_order_value: float
```

---

## 输出质量检查清单

- [ ] **DDD**：所有类名、字段名是否对应真实业务语义？枚举是否用业务术语？
- [ ] **DRY**：是否扫描了跨类重复字段和方法，提炼为 Interface？
- [ ] **O/C**：核心类是否稳定封闭？扩展是否用组合而非直接修改核心？
- [ ] **PECS**：批量操作参数是否用 Interface 类型（逆变）？返回值是否用具体类型（协变）？
- [ ] **继承关系**：是否识别并正确表达了类之间的继承关系（is-a）？子类是否使用 `class Child(Parent):` 语法？
- [ ] **继承 vs 组合**：是否正确区分了继承（is-a）和组合（has-a）的使用场景？
- [ ] **子类字段**：子类是否避免了重复定义父类已有的字段和方法？
- [ ] **继承标注**：子类 docstring 是否标注了 `Extends: ParentClass`？
- [ ] 所有外键是否用 `_rid` 后缀明确标注？
- [ ] Operation 是否都有 docstring 标注类型？
- [ ] 导航属性是否设置 `repr=False` 避免循环引用？
- [ ] 是否输出了关联关系图（包含继承关系）？
- [ ] 是否输出了四原则应用说明节？
