---
title: "使用 SKILL 自动生成模拟电路原理图"
date: 2026-06-25
draft: false
categories: ["模拟IC自动化设计"]
tags: ["模拟IC", "Cadence Virtuoso", "SKILL", "EDA自动化", "原理图生成", "AI Agent", "Spectre", "IC自动化设计", "Virtuoso", "原理图自动生成"]
---

# 使用 SKILL 自动生成模拟电路原理图

## 1. 背景：为什么需要自动生成原理图

在传统模拟 IC 设计流程中，原理图通常由设计者在 Cadence Virtuoso Schematic Editor 中手工绘制。对于单个电路和少量参数调整，这种方式直观、高效，也便于设计者结合经验进行局部修改。但当设计任务进入自动化生成、批量参数扫描、多轮仿真优化和 AI Agent 辅助设计时，纯 GUI 流程会逐渐成为瓶颈。

主要问题包括：

- 难以批量生成不同尺寸、不同偏置或不同补偿参数的电路；
- 难以与 Bayesian Optimization、TPE、gm-Id sizing 等优化算法形成闭环；
- 手工修改容易引入结构漂移，难以保证不同 trial 之间拓扑一致；
- GUI 操作不适合被 AI Agent、CI-like smoke test 或脚本化流程稳定调用；
- 多轮仿真迭代中，重复放置器件、改参数、保存检查的成本很高。

因此，模拟 IC 自动化设计需要把“画原理图”抽象成一个可编程过程：输入拓扑、参数和工艺映射，输出 Virtuoso 中可检查、可仿真、可继续编辑的 schematic。上一篇文章介绍了如何通过 virtuoso-bridge 建立 Python / AI Agent 到 Virtuoso 的调用通道；本文进一步讨论连接 Virtuoso 之后，如何使用 SKILL 自动创建模拟电路原理图。

## 2. SKILL 在 Virtuoso 自动化中的作用

SKILL 是 Cadence Virtuoso 的脚本语言。它可以直接访问 Virtuoso 的设计数据库对象，因此非常适合完成原理图自动化中的底层操作，例如：

- 创建或打开 library；
- 创建 schematic、symbol 等 cellview；
- 打开 PDK 或 analogLib 中的器件 symbol master；
- 放置 MOS、电阻、电容、电流源、电压源等 instance；
- 设置器件 CDF 参数；
- 创建 terminal、net、pin 和 wire；
- 添加 net label；
- 执行 `schCheck`；
- 保存并关闭 cellview。

在自动化系统中，SKILL 不一定负责全部业务逻辑。更合理的分工是：Python 负责拓扑描述、参数管理、优化调度和结果分析；SKILL 负责 Virtuoso 内部数据库操作。二者通过 virtuoso-bridge 或类似接口连接后，可以把原本依赖 GUI 的设计动作转化为可复现的工程流程。

## 3. Virtuoso 原理图的数据结构

要自动生成 schematic，首先需要理解 Virtuoso 中几个基本对象的关系。

### 3.1 Library、Cell 与 View

Virtuoso 的设计数据通常组织为：

```text
Library
  └── Cell
        ├── schematic view
        ├── symbol view
        ├── layout view
        └── 其他 view
```

`Library` 是设计单元集合，通常对应一个 OA library。`Cell` 表示一个电路模块，例如一个 OTA、bandgap、bias block 或 testbench。`View` 表示该 cell 的不同表达形式，其中 schematic view 是原理图，symbol view 是上层调用该电路时使用的符号。

自动生成原理图时，常见动作是打开或创建：

```skill
cv = dbOpenCellViewByType("myLib" "ota_auto" "schematic" "schematic" "a")
```

这里的 `cv` 是 cellview 句柄，后续 instance、wire、net、pin 都会创建在这个对象中。

### 3.2 Instance、Net、Pin 与 Wire

原理图不是一张普通图片，而是由数据库对象构成的连接图：

- `Instance`：器件或子模块实例，例如 `M1`、`R0`、`C1`、`I0`；
- `Terminal / Pin`：cell 对外暴露的端口，例如 `vinp`、`vinn`、`vout`、`VDD`；
- `Net`：电气网络名称，例如 `voutp`、`vbias`、`gnd!`；
- `Wire`：原理图中的连线图形对象，同时用于表达可读的连接关系；
- `Label`：网络名标注，通常贴在 wire 上。

从仿真角度看，连接关系最重要；从工程维护角度看，可读性也同样重要。自动生成的 schematic 不应只是“能 netlist”，还应方便设计者检查差分对、电流镜、偏置支路、CMFB、补偿网络等结构。

### 3.3 CDF 参数与器件属性

PDK 器件往往通过 CDF 参数描述尺寸和仿真属性。MOS 管可能有 `w`、`l`、`nf`、`m`、`fw`、`totalM` 等参数，具体名称取决于 PDK。不同工艺库的参数命名可能不同，不能假设所有 PDK 都使用同一套字段。

因此，自动化系统中最好引入 technology mapping 层，把“设计参数”与“PDK CDF 参数”隔离。例如：

```text
设计变量 width_in
        ↓
技术映射层查表
        ↓
PDK 中实际 CDF 字段 w / wf / width / totalWidth
```

这样在迁移 PDK 时，优化器和拓扑描述不需要大幅修改，只需更新工艺映射和器件 master 配置。

### 3.4 Schematic 与 Symbol 的关系

schematic 描述电路内部连接，symbol 描述该电路被上层调用时的接口。自动化生成电路时，必须保证二者端口一致：

- schematic 中的 terminal 名称应与 symbol pin 名称一致；
- 输入、输出、电源、地、偏置端口方向应合理；
- testbench 中调用 DUT symbol 时，pin name 和 net name 应对应清楚；
- 修改端口后，应重新检查 symbol 与 schematic 的一致性。

如果 schematic 和 symbol 不一致，后续 Maestro/OCEAN/Spectre 可能出现 netlist 错误、端口悬空或 stimulus 接错的问题。

## 4. 自动生成原理图的基本流程

### 4.1 创建或打开 Library

自动生成前需要确认目标 library 已存在，并且 `cds.lib` 能正确映射到该 library。实际工程中，library 的创建和 tech library 绑定通常应由专门的初始化脚本完成，而不是在每次生成 cell 时临时处理。

### 4.2 创建 CellView

生成脚本需要明确是覆盖旧 schematic，还是在新 cell 中生成。公开工程实践中更推荐保守策略：

- 原始人工设计 cell 不直接覆盖；
- 自动生成结果写入带后缀的新 cell，例如 `_auto`、`_gen`、`_check`；
- 若必须覆盖，应先备份或由上层流程显式确认。

简化示意：

```skill
cv = dbOpenCellViewByType("myLib" "ota_auto" "schematic" "schematic" "w")
unless(cv
  error("Could not open target schematic.\n")
)
```

### 4.3 放置器件 Instance

放置器件前，需要打开对应的 symbol master：

```skill
mosMaster = dbOpenCellViewByType("pdkLib" "nmos" "symbol")
inst = dbCreateInst(cv mosMaster "M1" 0:0 "R0")
```

不同项目中也可以使用 `schCreateInst`。关键点不是具体函数名，而是需要稳定管理：

- instance name；
- master cell；
- 坐标；
- 旋转方向；
- 所属模块区域。

器件应放在合理网格上。差分信号、电流镜、偏置支路、输出级、CMFB 和补偿网络最好分区摆放。自动生成的版式不必完全等同手工绘制，但应避免所有器件堆叠在原点，也应避免关键网络跨区混乱。

### 4.4 设置 MOS 管参数

MOS 参数设置通常通过 CDF 或对象属性完成。简化示意：

```skill
dbReplaceProp(inst "w" "string" "10u")
dbReplaceProp(inst "l" "string" "180n")
dbReplaceProp(inst "m" "string" "1")
```

在真实 PDK 中，更稳妥的做法是先读取 instance CDF，再确认参数名存在后写入。这样可以避免参数名拼错时脚本静默失败。对于 gm-Id 或优化流程，Python 侧可以输出物理尺寸，SKILL 侧只负责把这些尺寸写回到对应 instance。

### 4.5 创建端口与网络

自动生成原理图时，应把外部端口与内部网络区分清楚。典型端口包括：

- 输入：`vinp`、`vinn`；
- 输出：`voutp`、`voutn`；
- 电源：`VDD`、`VSS` 或 `gnd!`；
- 偏置：`ibias`、`vbias`、`vcm`；
- 控制：`enable`、`cmfb` 等。

差分电路中尤其要保持命名对称，例如 `vinp/vinn`、`voutp/voutn`、`clp/cln`。命名不对称会增加后续 metric extraction 和 testbench 生成的复杂度。

### 4.6 添加 wire 和 net name

一个常见误区是：自动化脚本只创建连接关系或只在器件 pin 附近贴 net name。这样虽然有时可以通过 netlist，但可读性较差，也容易在复杂电路中产生误连。

更好的做法是：

- 为关键 pin 创建短 wire stub；
- 将 net label 标注在 wire 上，而不是随意贴在器件本体上；
- 对差分输入、输出、电源、偏置和 CMFB 等关键网络使用清晰命名；
- 对复杂模块采用分区布局，减少 label 交叉和视觉歧义。

简化示意：

```skill
wire = schCreateWire(
  cv "draw" "direct"
  list(list(0.0 0.0) list(0.5 0.0))
  0.0 0.0 0.0
)

dbCreateLabel(
  cv list("wire" "label")
  list(0.25 0.0)
  "vout"
  "lowerCenter" "R0" "stick" 0.0625
)
```

不一定需要把所有 wire 绘制成手工原理图那样完整，但至少应让关键连接关系清晰可查。自动生成 schematic 的目标是“可仿真 + 可检查”，不是只追求最短脚本。

### 4.7 保存并检查 schematic

生成完成后应执行检查和保存：

```skill
checkResult = schCheck(cv)
dbSave(cv)
```

工程上应把 `schCheck` 的结果传回 Python 侧，并作为流程 checkpoint。若出现 error，不应继续进入 Spectre 仿真；若只有 warning，也需要判断是否会影响 netlist 或仿真有效性。

## 5. Python + SKILL 的协同方式

### 5.1 Python 负责参数组织

Python 适合处理结构化数据、配置文件和优化循环。一个简化的设计描述可以写成：

```python
design = {
    "library": "myLib",
    "cell": "ota_auto",
    "devices": [
        {"name": "M1", "type": "nmos", "w": "10u", "l": "180n"},
        {"name": "M2", "type": "nmos", "w": "10u", "l": "180n"},
    ],
    "nets": [
        ("vinp", "M1", "G"),
        ("vinn", "M2", "G"),
        ("vout", "M1", "D"),
    ],
}
```

这段代码只表达思想，不对应任何真实工程实现。实际项目中还需要包含器件 master、pin order、端口方向、坐标、旋转、参数合法性检查和工艺映射。

### 5.2 SKILL 负责 Virtuoso 数据库操作

SKILL 侧负责把结构化描述落实到 Virtuoso 数据库中。最小化示意如下：

```skill
cv = dbOpenCellViewByType("myLib" "ota_auto" "schematic" "schematic" "a")
mosMaster = dbOpenCellViewByType("pdkLib" "nmos" "symbol")

inst = dbCreateInst(cv mosMaster "M1" 0:0 "R0")
dbReplaceProp(inst "w" "string" "10u")
dbReplaceProp(inst "l" "string" "180n")

dbSave(cv)
```

真实工程中应加入 master 打开失败检查、CDF 参数名检查、wire/label 创建、terminal 创建、`schCheck` 和异常处理。

### 5.3 通过 virtuoso-bridge 执行 SKILL

Python 可以通过 virtuoso-bridge 调用 SKILL：

```python
from virtuoso_bridge import VirtuosoClient

client = VirtuosoClient.from_env()
result = client.execute_skill('getCurrentTime()')
print(result)
```

对于较长的原理图生成脚本，更推荐生成 `.il` 文件并加载：

```python
from virtuoso_bridge import VirtuosoClient

client = VirtuosoClient.from_env()
result = client.load_il("generate_schematic.il")
print(result)
```

这样便于版本管理、调试和复用，也避免把大量 SKILL 字符串拼接在 Python 源码中。

### 5.4 从拓扑描述到原理图生成

自动化原理图生成可以抽象为：

```text
拓扑描述 + 器件参数 + 工艺库信息
        ↓
Python 生成结构化设计数据
        ↓
转换为 SKILL 命令或 SKILL 脚本
        ↓
Virtuoso 执行 SKILL
        ↓
生成 schematic / symbol / testbench
```

在我的工程实践中，一个重要经验是把 topology 与 sizing 分离。拓扑决定“哪些器件存在、它们如何连接”；参数决定“每个器件的尺寸、倍乘数、finger 数、偏置和补偿值”。优化器应主要改变参数，而不应随意破坏拓扑结构。

可以用下面的形式描述：

```text
Circuit = Topology + Parameters + Technology Mapping
```

或者：

```text
C = G(V, E) + P
```

其中，`G(V, E)` 表示由器件节点和连接边构成的电路拓扑图，`P` 表示器件尺寸、倍乘数、finger 数、偏置电流、补偿电阻和补偿电容等设计变量。Technology Mapping 则负责把抽象器件和参数映射到具体 PDK 的 master cell 与 CDF 字段。

## 6. 一个简化的自动生成流程示例

下面给出一个抽象流程，展示 Python 与 SKILL 如何协同。示例经过简化，仅用于说明方法，不包含任何真实工程实现细节。

Python 侧生成设计数据：

```python
def build_design(width: str, length: str) -> dict:
    return {
        "library": "myLib",
        "cell": "ota_auto",
        "ports": ["vinp", "vinn", "vout", "vdd", "vss"],
        "devices": [
            {"name": "M1", "kind": "nmos", "w": width, "l": length, "xy": (0, 0)},
            {"name": "M2", "kind": "nmos", "w": width, "l": length, "xy": (2, 0)},
        ],
        "connections": [
            {"net": "vinp", "inst": "M1", "pin": "G"},
            {"net": "vinn", "inst": "M2", "pin": "G"},
            {"net": "vout", "inst": "M1", "pin": "D"},
        ],
    }
```

SKILL 侧执行创建动作：

```skill
procedure(CreateSimpleSchematic()
  let((cv mosMaster inst checkResult)
    cv = dbOpenCellViewByType("myLib" "ota_auto" "schematic" "schematic" "w")
    unless(cv error("open schematic failed\n"))

    mosMaster = dbOpenCellViewByType("pdkLib" "nmos" "symbol")
    unless(mosMaster error("open MOS master failed\n"))

    inst = dbCreateInst(cv mosMaster "M1" 0:0 "R0")
    dbReplaceProp(inst "w" "string" "10u")
    dbReplaceProp(inst "l" "string" "180n")

    checkResult = schCheck(cv)
    dbSave(cv)
    list("done" checkResult)
  )
)
```

真实系统会比这个示例复杂得多：它需要处理 PDK 器件映射、连接关系、terminal、wire、label、symbol、testbench、错误恢复和日志记录。但从架构上看，核心仍然是“结构化设计数据 -> SKILL 数据库操作 -> Virtuoso schematic”。

## 7. 在模拟 IC 优化闭环中的作用

自动生成原理图是模拟 IC 自动化闭环中的关键一环。完整流程通常包括：

```text
拓扑选择
  ↓
参数初始化或 gm-Id sizing
  ↓
SKILL 自动生成 schematic / testbench
  ↓
Spectre/OCEAN 自动仿真
  ↓
Python 提取指标
  ↓
优化器更新参数
  ↓
回写 schematic 或生成下一轮 netlist
```

在这个闭环中，原理图生成承担两个作用：

第一，它把抽象设计变量落地到 Virtuoso 数据库，使设计仍然保留在工业 EDA 工具链中，而不是只存在于外部 netlist 文件里。

第二，它为后续 testbench、symbol、Maestro、OCEAN、layout 辅助设计和人工审查提供统一入口。自动化系统不应绕开 Virtuoso，而应让 Virtuoso 成为可编程基础设施的一部分。

## 8. 工程实践中的注意事项

### 8.1 PDK 器件名和 CDF 参数名必须正确

不同 PDK 的 MOS master 名、symbol view、CDF 参数名可能不同。脚本中不应把所有 PDK 细节硬编码在优化器里，而应通过工艺配置或 technology mapping 层统一管理。

### 8.2 topology 与 sizing 应分离

拓扑描述决定器件和网络关系，sizing 参数决定尺寸和偏置。优化器每轮 trial 应只更新允许变化的参数，不应无意中删除器件、交换差分端口或改变关键连接关系。

### 8.3 instance、net、terminal 命名要规范

命名规范会直接影响后续仿真、指标提取和报告生成。差分信号建议保持成对命名，如 `vinp/vinn`、`voutp/voutn`。偏置、电源、地和 CMFB 网络也应使用稳定名称，避免每次生成出现不同别名。

### 8.4 wire 与 label 影响可读性和检查效率

自动 schematic 不一定要追求手工美观，但必须清楚。关键 pin 应通过短 wire stub 引出，net label 应贴在 wire 上。差分输入、输出、电源、偏置和补偿网络应尽量分区摆放，避免所有网络都依赖密集 label 隐式连接。

### 8.5 schematic 与 symbol 端口要一致

如果自动生成了 schematic，却没有同步 symbol，testbench 调用时很容易出错。建议把 symbol pin 检查作为生成流程的一部分，至少验证 pin 名称和方向是否与 schematic terminal 匹配。

### 8.6 避免反复覆盖人工修改内容

自动化脚本应明确写入目标。对人工维护的 golden schematic，应优先生成副本或独立 cell；若要回写优化结果，应只回写尺寸和偏置等可控参数，并保留日志。

### 8.7 每次生成后都要检查和验证

生成完成后至少执行：

- `schCheck`；
- `dbSave`；
- 必要时生成 netlist；
- 对最小 testbench 跑一次 Spectre smoke；
- 将错误、warning 和生成摘要返回 Python。

只有 schematic 能通过基本检查，才应进入后续优化和批量仿真。

### 8.8 为后续 Spectre 和版图自动化预留接口

原理图自动生成不应只服务当前仿真。器件命名、参数命名、模块分区和端口定义还会影响：

- Spectre/OCEAN testbench；
- operating point 提取；
- gm-Id 分析；
- 版图约束；
- 后仿真 backannotation；
- AI Agent 的错误定位和设计修改。

因此，schematic generator 的输出应尽量稳定、可读、可追踪。

## 9. 小结

使用 SKILL 自动生成模拟电路原理图，本质上是把 Virtuoso 中的 GUI 操作转化为可编程数据库操作。Python 负责组织拓扑、参数和优化流程；SKILL 负责在 Virtuoso 中创建 cellview、instance、net、pin、wire 和 label；Spectre/OCEAN 负责仿真和指标提取；AI Agent 可以在更高层参与流程控制、脚本生成、错误修复和设计策略调整。

一个清晰的职责划分如下：

| 层次 | 主要职责 |
|---|---|
| Python | 参数管理、拓扑描述、批量任务调度、优化算法、结果分析 |
| SKILL | Virtuoso 数据库操作、器件放置、连线、端口、保存检查 |
| Spectre/OCEAN | 仿真执行与性能提取 |
| AI Agent | 高层流程控制、脚本生成、错误修复、设计策略调整 |

本文完成了从结构化电路描述到 Virtuoso schematic 自动生成的方法说明。下一步，自动化流程需要进一步解决如何对生成的电路自动运行 Spectre 仿真、提取 AC / DC / Transient 指标，并将结果反馈给优化器。因此，下一篇文章将介绍基于 Spectre/OCEAN 的模拟电路自动仿真与结果管理流程。
