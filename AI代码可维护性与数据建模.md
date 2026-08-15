# AI 代码可维护性与数据建模

> 本文整理自一次关于“代码可维护性、数据结构，以及 AI 生成代码为何容易逐渐臃肿”的讨论。

## 1. 什么是代码的可维护性

代码的可维护性，是指未来的开发者（也包括未来的自己）能否以较低成本：

- 看懂代码的意图；
- 定位和修复问题；
- 修改已有需求；
- 添加新功能；
- 验证修改没有破坏其他功能；
- 在团队和系统持续变化时继续稳定开发。

简而言之：

> 可维护性衡量的不是代码今天能不能运行，而是它以后能不能被安全、持续地修改。

### 1.1 一个简单例子

下面的代码虽然能运行，但含义不清楚：

```python
def f(x, y, z):
    if z == 1:
        return x * 0.8 + y
    return x + y
```

存在的问题：

- `f` 的职责不明确；
- `x`、`y`、`z` 的含义不明确；
- `0.8` 是没有解释的魔法数字；
- `z == 1` 所代表的业务状态不明确。

改成下面这样，意图就清楚得多：

```python
VIP_DISCOUNT_RATE = 0.8


def calculate_order_total(product_price, shipping_fee, is_vip):
    if is_vip:
        discounted_price = product_price * VIP_DISCOUNT_RATE
        return discounted_price + shipping_fee

    return product_price + shipping_fee
```

这两段代码功能相近，但第二段代码更容易阅读、修改和测试，因此可维护性更高。

## 2. 高可维护性代码的主要特征

### 2.1 意图清楚

函数、变量、类型和模块名称能够准确表达业务含义，而不是依赖读者猜测。

### 2.2 职责明确

一个函数、类或模块只承担合理范围内的职责。例如，不要让同一个函数同时负责：

- 参数校验；
- 数据库查询；
- 业务计算；
- 支付请求；
- 状态更新；
- 日志和通知。

可以将流程拆成语义明确的步骤：

```python
validate_order()
reserve_inventory()
process_payment()
create_order()
```

### 2.3 业务规则集中

同一条业务规则不应复制到多个文件。规则散落后，不同位置很容易产生细微差异。

### 2.4 依赖和影响范围可控

修改一个模块时，不应意外破坏大量无关功能。模块边界和依赖方向应当清楚。

### 2.5 容易测试和验证

核心逻辑应能独立测试，而不是每次都必须启动数据库、网络服务和完整 UI。

```python
def calculate_discount(price, discount_rate):
    return price * discount_rate


assert calculate_discount(100, 0.8) == 80
```

### 2.6 容易排查问题

系统应具备有意义的错误、日志和可复现测试，能够回答：

- 哪里失败了？
- 输入是什么？
- 执行到了哪一步？
- 为什么失败？

## 3. 可维护性不等于什么

### 3.1 不等于代码越短越好

过度压缩可能减少行数，却增加理解成本。代码应优先清楚，而不是追求炫技。

### 3.2 不等于注释越多越好

注释不应重复代码已经表达的内容：

```python
# 给数量加一
count += 1
```

有价值的注释应解释“为什么”：

```python
# 支付平台最多允许重试三次，继续重试可能造成重复扣款。
MAX_PAYMENT_RETRIES = 3
```

### 3.3 不等于抽象越多越好

接口、工厂、注册表、基类和设计模式不是越多越好。抽象只有在能够降低真实复杂度时才有价值。

如果一个字典可以清楚解决问题，就不必创建多层 `Factory`、`Manager`、`Provider` 和 `Registry`。

### 3.4 不等于完全消除重复

两段代码看起来相似，不代表它们属于同一个业务概念。只有当它们会因为同一种原因而变化时，合并抽象通常才合理。

## 4. 数据结构为什么会影响可维护性

程序可以粗略理解为：

> 程序 = 数据的组织方式 + 操作数据的逻辑。

如果数据结构符合真实问题，处理逻辑通常会比较简单；如果数据组织错误，后续逻辑就不得不用大量循环、判断和临时变量进行补救。

因此，设计代码时不要只问：

> 这个函数应该怎么写？

还要先问：

> 数据之间是什么关系？系统将以什么方式访问和修改这些数据？

## 5. 合适的数据结构如何减少臃肿代码

### 5.1 用映射表代替纯映射型条件分支

如果分支只是在表达“输入 A 对应输出 B”，它本质上通常是一张映射表。

```python
def get_discount(user_type):
    if user_type == "normal":
        return 1.0
    elif user_type == "vip":
        return 0.8
    elif user_type == "svip":
        return 0.7
    elif user_type == "employee":
        return 0.5
    return 1.0
```

可以改为：

```python
DISCOUNT_RATES = {
    "normal": 1.0,
    "vip": 0.8,
    "svip": 0.7,
    "employee": 0.5,
}


def get_discount(user_type):
    return DISCOUNT_RATES.get(user_type, 1.0)
```

这不仅减少代码，也明确表达了“用户类型到折扣率”的映射关系。

### 5.2 用集合表达成员和集合关系

```python
if role == "admin" or role == "owner" or role == "superuser":
    allow()
```

可以改为：

```python
PRIVILEGED_ROLES = {"admin", "owner", "superuser"}

if role in PRIVILEGED_ROLES:
    allow()
```

集合适合表达：

- 去重；
- 成员判断；
- 交集、并集和差集；
- 子集和包含关系。

### 5.3 用业务对象代替平行数组

下面的多个数组必须依靠相同下标维持关联，很容易出现错位：

```python
names = ["Alice", "Bob"]
ages = [20, 25]
emails = ["alice@example.com", "bob@example.com"]
```

更合理的组织方式是：

```python
from dataclasses import dataclass


@dataclass
class User:
    name: str
    age: int
    email: str


users = [
    User("Alice", 20, "alice@example.com"),
    User("Bob", 25, "bob@example.com"),
]
```

### 5.4 根据访问模式建立索引

如果系统经常按用户 ID 查找用户，却始终使用列表扫描：

```python
def find_user(users, user_id):
    for user in users:
        if user.id == user_id:
            return user
    return None
```

可以为主要查询模式建立索引：

```python
users_by_id = {user.id: user for user in users}
user = users_by_id.get(user_id)
```

这不仅改善性能，也明确表达了“用户由唯一 ID 标识，系统主要按 ID 访问用户”。

### 5.5 根据关系对数据分组

```python
from collections import defaultdict

orders_by_user_id = defaultdict(list)

for order in orders:
    orders_by_user_id[order.user_id].append(order)
```

当后续逻辑经常需要“某个用户的全部订单”时，分组结构能避免反复扫描全部订单。

### 5.6 用队列表达先进先出

队列适合任务调度、消息处理、请求缓冲和广度优先搜索。选择队列不仅是性能问题，也是在代码中表达处理语义。

### 5.7 用树表达层级

树适合文件目录、菜单、组织架构、DOM 和评论回复等天然具有父子层级的数据。

### 5.8 用图表达复杂关系和状态转换

订单或任务状态之间的合法转换可以用图式结构集中表达：

```python
ALLOWED_TRANSITIONS = {
    "created": {"paid", "cancelled"},
    "paid": {"shipped", "refunded"},
    "shipped": {"completed", "refunded"},
    "completed": set(),
    "cancelled": set(),
    "refunded": set(),
}


def can_transition(current_status, next_status):
    return next_status in ALLOWED_TRANSITIONS[current_status]
```

这样，状态规则不必散落在大量 `if/else` 中。

## 6. 常见数据结构的选择原则

### List

适合：

- 保持顺序；
- 允许重复元素；
- 按位置访问；
- 依次遍历。

### Set

适合：

- 去重；
- 快速成员判断；
- 集合运算。

### Map / Dict

适合：

- 根据唯一键查找；
- 表达键值映射；
- 建立索引；
- 避免反复遍历列表。

### Queue

适合先进先出的任务处理。

### Stack

适合后进先出、撤销操作、嵌套结构解析和深度优先处理。

### Tree

适合层级数据。

### Graph

适合路线、依赖、社交关系、工作流和状态转换。

### 对象、结构体和数据类

适合表达明确的业务实体、字段关系和约束。

## 7. AI 生成代码为什么容易逐渐变成“屎山”

AI 生成代码时，往往面对的是一个局部任务：

- 增加一个按钮；
- 增加一个状态；
- 修复一个判断；
- 支持一种新类型；
- 展示一项接口数据。

在缺少工程约束时，AI 容易选择“改动最小、立即跑通”的方式：

```python
if type == "a":
    ...
elif type == "b":
    ...
elif type == "c":
    ...
```

下一次需求来了，就继续追加一个分支。每次修改单独看都能运行，但整体结构会持续恶化。

这可以概括为：

> 局部最优，整体恶化。

问题并不只是“AI 使用的数据结构少”，而是：

> AI 经常缺少持续的数据建模过程，只完成当前动作，没有维护统一的数据模型、业务边界和系统不变量。

## 8. AI 代码常见的数据建模问题

### 8.1 万物皆字典

AI 很容易使用无约束字典快速拼接功能：

```python
def process_user(user):
    if user["type"] == "vip" and user["status"] == "active":
        if user.get("level", 0) > 2:
            ...
```

问题包括：

- 字段没有类型约束；
- 字段可能缺失；
- 合法状态组合不清楚；
- 字段重命名难以安全重构；
- 业务规则容易散落。

可以使用枚举和数据类明确建模：

```python
from dataclasses import dataclass
from enum import Enum


class UserType(Enum):
    NORMAL = "normal"
    VIP = "vip"


class UserStatus(Enum):
    ACTIVE = "active"
    DISABLED = "disabled"


@dataclass
class User:
    user_type: UserType
    status: UserStatus
    level: int

    @property
    def has_advanced_vip_access(self) -> bool:
        return (
            self.user_type is UserType.VIP
            and self.status is UserStatus.ACTIVE
            and self.level > 2
        )
```

### 8.2 使用列表保存一切

如果业务主要按键查找数据，却始终保存为列表，就会到处出现线性扫描和重复查找。

### 8.3 使用多个布尔值模拟互斥状态

```python
is_started = True
is_processing = False
is_finished = False
is_failed = False
is_cancelled = False
```

这种结构允许大量矛盾组合。一个任务如果同一时刻只能处于一个状态，应优先使用枚举或状态机：

```python
class TaskStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
```

### 8.4 用裸字符串表达有限状态

状态、类型、操作类型和模式如果只有固定取值，不应在各处散落字符串字面量。枚举和明确类型可以减少拼写错误，并支持安全重构。

### 8.5 将数据映射写成控制流程

当大量 `if/elif` 只负责返回固定值时，通常应考虑映射表、配置或策略注册表。

### 8.6 不建立索引和派生结构

AI 为了快速跑通，可能生成双层循环：

```python
for order in orders:
    for user in users:
        if order.user_id == user.id:
            ...
```

更合理的方式通常是先建立索引：

```python
users_by_id = {user.id: user for user in users}

for order in orders:
    user = users_by_id.get(order.user_id)
    ...
```

### 8.7 同一业务条件不断复制

规则在多个调用点复制后，会出现漏改和细微差异。应把规则放到明确的策略、领域对象或服务中，并建立统一入口。

## 9. “屎山代码”是如何逐渐形成的

代码通常不是一次性写坏的，而是经过很多次看似合理的小修改积累而成。

第一次需求：

```python
if user.is_vip:
    apply_discount()
```

后来不断增加条件：

```python
if (
    user.is_vip
    and user.level >= 3
    and not user.is_expired
    and region != "restricted"
    and product.type != "special"
):
    apply_discount()
```

当这段判断又被复制到多个文件时，不同位置就会逐渐产生差异。

此时真正需要的不是继续格式化条件，而是提取业务概念：

```python
class DiscountPolicy:
    def is_eligible(self, user, product, region) -> bool:
        return (
            user.has_active_vip_membership
            and user.level >= self.minimum_level
            and region not in self.restricted_regions
            and product.type not in self.excluded_product_types
        )
```

调用方只需要关心：

```python
if discount_policy.is_eligible(user, product, region):
    apply_discount()
```

其根因可以概括为：

> 每次都在原有结构上增加一个判断，却没有在复杂度达到临界点时重新审视和整理数据模型。

## 10. 让非法状态不可表示

这是数据建模中非常实用的原则。

下面的支付模型允许很多矛盾组合：

```python
@dataclass
class Payment:
    is_pending: bool
    is_successful: bool
    is_failed: bool
    error_message: str | None
    transaction_id: str | None
```

例如，它可能同时处于成功和失败状态，也可能成功却没有交易号。

至少可以先使用枚举压缩状态空间：

```python
class PaymentStatus(Enum):
    PENDING = "pending"
    SUCCESSFUL = "successful"
    FAILED = "failed"
```

更严格时，可以用不同类型表示不同状态：

```python
@dataclass
class PendingPayment:
    payment_id: str


@dataclass
class SuccessfulPayment:
    payment_id: str
    transaction_id: str


@dataclass
class FailedPayment:
    payment_id: str
    error_message: str
```

由此可以保证：

- 成功支付一定有交易号；
- 失败支付一定有错误信息；
- 不再需要到处检查可选字段；
- 大量非法组合从模型层面被消除。

好的数据模型会直接减少防御性代码和条件分支。

## 11. 数据结构、数据模型和架构的区别

这三个概念相互关联，但不能混为一谈。

### 11.1 数据结构

解决数据如何组织和访问：

- 列表；
- 集合；
- 字典；
- 队列；
- 栈；
- 树；
- 图；
- 堆。

### 11.2 数据模型

解决业务中有哪些实体、状态、关系和不变量：

- 用户；
- 订单；
- 商品；
- 权限；
- 工作流状态；
- 业务规则；
- 实体之间的一对一、一对多或多对多关系。

### 11.3 架构

解决模块如何划分和协作：

- 哪一层负责业务规则；
- 哪一层访问数据库；
- 哪一层处理 HTTP；
- 谁可以依赖谁；
- 状态由谁拥有；
- 副作用在哪里发生。

即使数据结构选择正确，如果系统存在循环依赖、全局可变状态、业务规则散落、UI 直接修改数据库等问题，代码仍然会难以维护。

## 12. 不要从一个极端走向另一个极端

不能简单要求 AI“多用数据结构和设计模式”。这可能让 AI 走向过度设计：

- 为一个简单映射创建多层工厂；
- 为唯一实现创建接口；
- 为假想需求提前建立庞大扩展体系；
- 将简单流程拆成大量跳转层；
- 用高级数据结构增加认知负担。

例如，税率映射可能只需要：

```python
TAX_RATES = {
    "CN": 0.13,
    "US": 0.08,
}
```

没必要自动扩展成：

```text
TaxRateProviderInterface
  └── DefaultTaxRateProvider
        └── TaxRateRepository
              └── TaxRateRegistry
                    └── TaxRateFactory
```

正确目标不是“高级”，而是：

> 使用最简单、最贴近业务的数据模型，消灭不必要的控制流程和重复规则。

## 13. 使用 AI 编码时应改变提问方式

不要只说：

> 帮我实现这个功能。

可以要求 AI 在编码前先分析问题：

```text
先不要写代码。请先分析这个需求中的实体、状态、不变量、查询模式和未来可能的变化方向，判断现有数据模型是否合适。给出最简单、可维护且不过度设计的方案，然后再实现。
```

### 13.1 编码前的数据建模问题

可以要求 AI 先回答：

1. 核心业务实体是什么？
2. 实体之间是一对一、一对多，还是多对多？
3. 哪些数据需要按键查找，哪些数据需要保持顺序？
4. 哪些状态互斥？
5. 哪些状态组合属于非法状态？
6. 哪些业务规则目前散落在条件分支中？
7. 哪些列表应该建立索引、集合或分组？
8. 哪些映射关系不应继续使用 `if/else`？
9. 这个需求最可能沿哪个方向变化？
10. 最简单且不过度设计的数据模型是什么？

### 13.2 可直接复用的 AI 编码约束

```text
实现时请遵守以下原则：

- 不使用平行数组；
- 不使用多个布尔值模拟互斥状态；
- 不使用裸字符串表达有限枚举；
- 不重复遍历同一列表完成按键查询；
- 不把相同业务条件复制到多个调用点；
- 纯映射关系优先使用映射表；
- 业务对象优先使用明确类型，而不是无约束字典；
- 根据主要访问模式选择数据结构并建立必要索引；
- 不为了假想需求引入多余抽象；
- 函数保持单一职责；
- 副作用与核心计算尽量分离；
- 为核心不变量和状态转换编写测试；
- 实现完成后检查重复规则、深层嵌套和非法状态。
```

## 14. 审查 AI 代码时的“屎山信号”

### 14.1 数据结构方面

- [ ] 同一个列表是否被反复线性查找？
- [ ] 是否存在多个依靠相同下标保持对应的数组？
- [ ] 是否用多个布尔变量表达一个互斥状态？
- [ ] 是否到处使用 `"pending"`、`"success"` 等裸字符串？
- [ ] 是否大量使用字段随意变化的无约束字典？
- [ ] 是否手写了本可由集合完成的去重和成员判断？
- [ ] 是否把固定映射写成很长的 `if/elif`？
- [ ] 是否每次调用都重复分组、排序或建立索引？
- [ ] 数据结构是否允许大量非法状态存在？

### 14.2 业务建模方面

- [ ] 同一条规则是否在多个文件重复出现？
- [ ] 对象是否只是数据袋，没有保护自身不变量？
- [ ] 状态转换是否合法，是否有统一入口？
- [ ] 函数参数是否越来越多，而且总是成组传递？
- [ ] 一个字段的含义是否依赖另一个字段，却没有明确类型？
- [ ] 是否存在大量 `None`、特殊值和隐式约定？

### 14.3 代码结构方面

- [ ] 一个函数是否同时做查询、计算、更新和通知？
- [ ] 是否存在超过三四层的条件嵌套？
- [ ] 是否通过全局可变状态传递上下文？
- [ ] 修改一条规则是否需要同步修改多个模块？
- [ ] 是否只有原作者知道代码为什么这样写？
- [ ] 是否必须依靠注释才能理解代码的基本意图？
- [ ] 单元测试是否必须启动整个系统才能运行？
- [ ] 是否存在“这段代码不要动，动了不知道哪里会坏”的区域？

## 15. 改善 AI 代码的工程流程

低质量流程通常是：

> 需求来了 → 找到一个位置 → 加判断 → 跑通 → 结束。

更好的流程是：

> 需求来了 → 识别它暴露出的业务概念 → 检查当前数据模型能否自然表达 → 必要时先整理模型 → 实现功能 → 用测试保护不变量和行为。

建议采用以下步骤：

1. **先理解需求和现有模型**：避免直接在局部追加逻辑。
2. **识别实体、关系、状态和不变量**：明确问题的真实结构。
3. **分析主要访问模式**：决定是否需要索引、集合、队列、树或图。
4. **寻找散落的业务规则**：将其集中到明确归属的位置。
5. **选择最简单的数据结构和模型**：不要为了“高级”而增加层级。
6. **先为关键行为和不变量建立测试**：为重构和修改提供安全网。
7. **实现当前需求**：保持控制流程简单、职责清楚。
8. **审查结构债务**：检查重复、嵌套、裸字符串、布尔状态和无约束字典。
9. **运行验证**：确认功能正确且没有破坏已有行为。

## 16. 总结

高可维护性的代码通常离不开合理的数据结构，但数据结构只是地基，不是全部。还需要同时关注：

- 数据模型；
- 状态设计；
- 业务不变量；
- 模块边界；
- 依赖方向；
- 副作用管理；
- 测试与验证；
- 恰当的重构时机。

AI 生成代码容易臃肿，并不主要是因为它不会使用某种高级数据结构，而是因为它经常只追求当前任务跑通，没有持续维护系统的整体模型。

最终可以记住以下几句话：

> 先把数据组织对，再写处理逻辑；很多复杂逻辑，其实是在替错误的数据结构擦屁股。

> 差代码把复杂度堆进控制流程；好代码先用数据模型吸收复杂度，让执行流程保持简单。

> 可维护性的目标不是展示技术难度，而是降低理解、修改和验证代码所需的成本。

> 数据结构不是越复杂越好，而是越贴合问题越好；抽象也不是越多越好，而是恰好能够控制真实变化。
