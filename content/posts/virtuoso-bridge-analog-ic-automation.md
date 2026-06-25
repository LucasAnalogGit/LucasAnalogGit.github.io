---
title: "virtuoso-bridge搭建与模拟IC自动化设计"
date: 2026-06-25
draft: false
categories: ["模拟IC自动化设计"]
tags: ["模拟IC", "Virtuoso", "SKILL", "Spectre", "EDA自动化", "AI Agent", "virtuoso-bridge", "IC自动化设计"]
---

# 基于 virtuoso-bridge 的 Cadence Virtuoso 自动化接口搭建

## 1. 背景：为什么模拟 IC 设计需要自动化接口

模拟 IC 设计长期依赖 Cadence Virtuoso 这样的交互式 GUI 环境。设计者在 schematic editor 中放置器件、连接网络、设置 ADE/Maestro 仿真、查看波形，再根据经验修改参数。这种流程对单次人工设计非常有效，但当设计任务进入参数扫描、批量仿真、自动优化、AI Agent 辅助生成电路等场景时，GUI 就会成为自动化链路中的瓶颈。

模拟电路自动化设计的核心问题并不是“完全替代设计者”，而是把重复、可描述、可验证的操作从手工点击转化为可编程接口。例如：

- 自动创建 library、cell 和 schematic；
- 根据拓扑描述生成器件实例和连线；
- 批量修改 MOS 尺寸、偏置电流、补偿网络参数；
- 自动运行 Spectre/OCEAN/Maestro 仿真；
- 从仿真结果中提取 gain、GBW、PM、SR、power 等指标；
- 将指标反馈给 Bayesian Optimization、TPE、gm-Id sizing 或 AI Agent，形成闭环优化。

在这个闭环中，Virtuoso 仍然是设计数据库、PDK、schematic、layout 和仿真配置的核心平台；Python 和 Agent 则负责高层调度、代码生成、参数搜索和结果分析。二者之间需要一个稳定接口。`virtuoso-bridge-lite` 的价值就在这里：它在 Virtuoso 外部建立一层可编程控制通道，使 Python 脚本或 AI Agent 可以通过 CLI 或 Python API 驱动 Virtuoso 执行 SKILL，并在合适配置下组织 Spectre 仿真与结果读取。

## 2. virtuoso-bridge 是什么

`virtuoso-bridge-lite` 是一个面向 Cadence Virtuoso 的自动化桥接项目。根据项目 README，它的定位是让 LLM Agent 或脚本能够在本地或远程环境中驱动 Cadence Virtuoso，用于 schematic、layout、Maestro、Spectre 等模拟/混合信号设计任务。

需要强调的是，virtuoso-bridge 不是 Virtuoso 的替代品，也不是新的 EDA 数据库。它的本质是：

> 在 Virtuoso 外部建立一个可编程控制层，使 Python 脚本、CLI 或 AI Agent 能够向 Virtuoso 中的 SKILL 环境发送表达式，并获得执行结果。

因此，它依赖已有的 Cadence 环境、PDK、license、Virtuoso 进程和 Spectre 安装。它解决的是接口问题：如何让外部自动化程序可靠地进入 Virtuoso/SKILL 世界，而不是让设计者在 GUI 中手动完成每一步。

从工程角度看，可以把它理解为四类能力的组合：

- SKILL 执行通道：执行 inline SKILL 或加载 `.il` 文件；
- 远程连接层：通过 SSH tunnel 将本地 Agent 与远程 EDA 服务器连接起来；
- 高层 Python API：封装 schematic、layout、window、snapshot 等常用操作；
- Spectre 运行与结果处理能力：在远程或本地环境中调用 Spectre，并处理部分仿真输出。

这些能力并不是强耦合的。项目文档明确指出，Virtuoso SKILL bridge 与 Spectre simulation 是相对独立的两条能力链路：可以只使用 Spectre runner，也可以只使用 SKILL bridge。

## 3. 核心原理：Python / SSH / TCP / SKILL / Virtuoso 的协同机制

virtuoso-bridge 的关键思想是把一次外部自动化请求拆成几层：Python 或 CLI 负责发起请求，TCP 或 SSH tunnel 负责传输，Virtuoso 中加载的 SKILL bridge 负责接收并执行，最终操作 Virtuoso 数据库或当前会话。

一个简化链路如下：

```text
AI Agent / Python Script
        ↓
virtuoso-bridge Python API / CLI
        ↓
SSH tunnel 或 localhost TCP
        ↓
Virtuoso 中加载的 SKILL bridge
        ↓
Cadence Virtuoso 数据库 / schematic / layout / Maestro
```

### 3.1 SKILL 执行链路

Python 侧的核心入口是 `VirtuosoClient`。在最基本的用法中，外部脚本通过：

```python
from virtuoso_bridge import VirtuosoClient

client = VirtuosoClient.from_env()
result = client.execute_skill("1+2")
print(result)
```

向 Virtuoso 发送一段 SKILL 表达式。`VirtuosoClient` 本身是一个 TCP SKILL client，它不直接理解 schematic 或 layout 的全部语义，而是把需要执行的 SKILL 代码发送到 bridge daemon，并等待结果返回。

Virtuoso 侧需要先加载项目提供的 `.il` 文件。`virtuoso-bridge start` 会部署相关 SKILL bridge 文件，并打印一条需要复制到 Virtuoso CIW 中执行的 `load(...)` 命令，例如：

```skill
load("/tmp/virtuoso_bridge_xxx/virtuoso_bridge/virtuoso_setup.il")
```

实际路径由当前用户、profile、remote host 和临时目录策略决定，应以命令行输出为准。加载之后，Virtuoso 的 SKILL 环境中会启动 bridge 相关服务。项目 README 中给出的底层机制包括 Cadence SKILL 的 `ipcBeginProcess`、`evalstring` 和 `ipcWriteProcess`：SKILL 侧通过 IPC 启动/连接进程，收到表达式后用 `evalstring` 在 Virtuoso SKILL 环境中求值，再把结果写回给外部程序。

这意味着外部程序最终执行的仍然是 Virtuoso 原生 SKILL。只要某个操作可以用 SKILL 表达，就有机会通过 bridge 被 Python 或 Agent 调用；但是否已经有高层封装，则取决于项目当前 API、skills 和 examples 的覆盖范围。

### 3.2 Local Mode 与 Remote Mode

EDA 环境常见的工作方式是：本地电脑运行编辑器或 Agent，Virtuoso 和 Spectre 运行在远程 Linux 设计服务器上。virtuoso-bridge 对这种场景提供 remote mode：

- 本地运行 `virtuoso-bridge start`；
- 通过 SSH 连接到远程 EDA 服务器；
- 建立本地端口到远程 daemon 的 tunnel；
- 用户在远程 Virtuoso CIW 中执行 `load(...)`；
- 本地 Python/Agent 通过 localhost port 访问远程 Virtuoso SKILL 环境。

如果 Virtuoso 就运行在本机，可以使用 local mode。按照项目文档，local mode 通常设置 `VB_REMOTE_HOST=localhost` 或使用本地端口，此时 SSH tunnel 可被跳过，Python 直接连到本机 bridge daemon。

两种模式的区别主要在传输层：remote mode 多了 SSH tunnel、远程文件部署和远程 shell 命令执行；local mode 则更接近 localhost TCP 通信。对上层 `execute_skill("...")` 来说，调用方式可以保持一致。

### 3.3 VirtuosoClient、SSHClient 与 SpectreSimulator 的分层关系

项目 README 对三层关系给出了清晰划分：

- `VirtuosoClient`：纯 TCP SKILL client，负责发送 SKILL 并接收结果，本身不关心 SSH；
- `SSHClient`：维护持久 SSH 连接和端口转发，可用于 remote mode 下的 tunnel、shell command 和文件传输；
- `SpectreSimulator`：通过 SSH shell command 运行 Spectre，并通过 rsync 等方式传输 netlist 与结果。

这种分层对模拟 IC 自动化非常重要。它避免把“控制 Virtuoso GUI/SKILL”和“运行 Spectre 仿真”混成一个不可分割的黑盒。实际工程中，某些任务只需要读取 netlist 并跑 Spectre，不需要打开 Virtuoso；另一些任务只需要在 schematic/layout 中做数据库操作，不需要跑仿真。分层之后，自动化脚本可以按需组合。

### 3.4 Virtuoso 与 Spectre 的独立性

Virtuoso 和 Spectre 在 Cadence 设计流程中经常一起出现，但从自动化接口看，它们是两类不同能力：

- Virtuoso/SKILL bridge：要求有正在运行的 Virtuoso 进程，并且 CIW 中已加载 bridge setup 文件；
- Spectre runner：要求远程或本地 shell 中能找到 `spectre`，或者通过 `VB_CADENCE_CSHRC` 设置 Cadence 工具环境。

因此，`virtuoso-bridge status` 会分别报告 tunnel、Virtuoso daemon 和 Spectre availability。调试时也应分开判断：`daemon` 不通通常意味着 CIW 没有加载 `load(...)` 或端口/tunnel 有问题；`spectre` 不可用通常意味着 PATH、license、Cadence cshrc 或远程 shell 环境有问题。

## 4. 环境搭建流程

### 4.1 前置条件

搭建前需要确认以下条件：

- 可以访问 Cadence Virtuoso，并有可用 license；
- 如果使用 remote mode，本地到远程 EDA 服务器的 SSH 能免交互登录；
- 远程或本地已有 Python 环境，推荐使用 `uv` 创建虚拟环境；
- 如果需要运行 Spectre，远程 shell 中能找到 `spectre`，或者准备好用于加载 Cadence 环境变量的 cshrc；
- Virtuoso 需要处于运行状态，后续要在 CIW 中执行 `load(...)`。

对于有跳板机的 EDA 环境，需要区分 jump host 与 compute host。`VB_REMOTE_HOST` 应指向真正运行 Virtuoso 的机器，而不是只负责跳转的堡垒机。

### 4.2 克隆仓库与创建 Python 虚拟环境

基础安装命令如下：

```bash
git clone https://github.com/Arcadia-1/virtuoso-bridge-lite.git
cd virtuoso-bridge-lite

uv venv .venv
source .venv/bin/activate
uv pip install -e .
```

项目文档推荐使用 `uv` 和虚拟环境，避免污染系统 Python。对于多人共用 EDA 服务器的环境，这一点尤其重要：不同项目、不同 PDK、不同自动化脚本的依赖应尽量隔离。

### 4.3 初始化配置文件

安装后可以生成配置文件：

```bash
virtuoso-bridge init
```

如果已经知道远程目标，也可以直接指定：

```bash
virtuoso-bridge init user@eda-server
```

带跳板机时可使用：

```bash
virtuoso-bridge init user@compute-host -J user@jump-host
```

默认配置通常写入 `~/.virtuoso-bridge/.env`。remote mode 下常见字段如下：

```bash
VB_REMOTE_HOST=
VB_REMOTE_USER=
VB_REMOTE_PORT=
VB_LOCAL_PORT=
VB_CADENCE_CSHRC=
```

含义可以按下面理解：

- `VB_REMOTE_HOST`：运行 Virtuoso 或 Spectre 的远程 EDA 服务器；
- `VB_REMOTE_USER`：远程服务器上的用户名；
- `VB_REMOTE_PORT`：远程 bridge daemon 使用的端口；
- `VB_LOCAL_PORT`：本地 SSH tunnel 暴露给 Python/Agent 的端口；
- `VB_CADENCE_CSHRC`：可选字段，用于在远程 shell 中加载 Cadence/Spectre 所需环境变量。

如果 `spectre` 已经在远程用户默认 PATH 中，`VB_CADENCE_CSHRC` 不一定需要设置；如果每次登录后必须 source 某个 `.cshrc` 才能使用 Cadence 工具，则应配置该字段。

### 4.4 启动 bridge

启动命令为：

```bash
virtuoso-bridge start
```

在 remote mode 下，该命令会建立 SSH tunnel，并部署 bridge 相关文件。重要的是，它通常会打印一条需要复制到 Virtuoso CIW 中执行的 `load(...)` 命令。不要手写这个路径，应该复制命令行实际输出。

常用生命周期命令包括：

```bash
virtuoso-bridge status
virtuoso-bridge stop
virtuoso-bridge restart
```

`status` 对调试很有用，因为它会检查 tunnel、Virtuoso daemon 和 Spectre availability。若 daemon 显示 no response，而 tunnel 正常，通常下一步就是确认 CIW 中是否已经加载了 `load(...)`。

### 4.5 在 Virtuoso CIW 中加载 SKILL bridge

启动 bridge 后，在 Virtuoso CIW 中执行类似下面的命令：

```skill
load("/tmp/virtuoso_bridge_xxx/virtuoso_bridge/virtuoso_setup.il")
```

加载成功后，Virtuoso 会拥有接收外部 SKILL 请求的 bridge 服务。项目文档中也提到，可以把该 `load(...)` 加入远程 `~/.cdsinit`，从而在每次启动 Virtuoso 时自动加载。不过在初次搭建和调试阶段，建议先手动加载，确认 profile、端口和路径没有问题。

如果同一个 CIW 中已经加载过旧 profile 或旧端口，切换前应先停止旧 daemon。项目文档提到可使用 `RBStop()` 或 `RBStopAll()` 停止已有 bridge 服务。

### 4.6 状态检查与最小测试

先检查整体状态：

```bash
virtuoso-bridge status
```

再运行最小 Python 测试：

```python
from virtuoso_bridge import VirtuosoClient

client = VirtuosoClient.from_env()
result = client.execute_skill("1+2")
print(result)
```

如果返回结果中能看到成功状态，并且输出为 `3`，说明 Python 到 Virtuoso SKILL 环境的基本链路已经打通。注意：`execute_skill()` 的返回值会回到 Python，并不一定自动打印到 CIW。如果希望 CIW 也显示信息，需要在 SKILL 表达式中显式使用 `printf`。

## 5. 常用命令与功能说明

virtuoso-bridge 提供 CLI-first 的使用方式，适合 AI Agent、VS Code task 或 shell script 调用。常见命令如下：

```bash
# 初始化配置
virtuoso-bridge init
virtuoso-bridge init user@host
virtuoso-bridge init user@compute-host -J user@jump-host

# tunnel 与 daemon 状态
virtuoso-bridge start
virtuoso-bridge status
virtuoso-bridge restart
virtuoso-bridge stop

# 执行 inline SKILL
virtuoso-bridge eval 'getCurrentTime()'

# 从 stdin 执行多行 SKILL
virtuoso-bridge eval --stdin <<'EOF'
let((libs)
  libs = mapcar(lambda((l) l~>name) ddGetLibList())
  printf("found %d libraries\n" length(libs))
  libs
)
EOF

# 加载完整 .il 脚本
virtuoso-bridge load my_script.il

# 查看 Virtuoso 窗口
virtuoso-bridge windows

# 截图或抓取当前窗口信息
virtuoso-bridge screenshot
virtuoso-bridge snapshot

# 检查 Spectre license 或可用性
virtuoso-bridge license
```

这些命令背后的共同点是：把原本需要在 CIW 或 GUI 中手动完成的动作，转成可以被脚本、任务系统或 Agent 调用的命令。对于自动化设计而言，这种 CLI 入口很关键，因为它可以被纳入 Makefile、CI-like smoke test、优化脚本、实验记录系统和 Agent toolchain。

## 6. 在模拟 IC 自动化设计中的典型应用

### 6.1 自动创建 library / cell / schematic

Virtuoso 数据库操作本质上可以通过 SKILL 完成。因此，借助 `execute_skill()` 或项目提供的 schematic API，可以自动化创建 library、cell、cellview，并生成 schematic。一个典型方向是：由 Python 中的电路拓扑描述生成 SKILL，调用 Virtuoso 创建器件实例、pin、wire 和 label。

在工程上，这可以支持“拓扑模板 + 参数表”的生成方式。例如两级运放、共源级、差分对、电流镜等模块，都可以先用结构化数据描述，再映射为 Virtuoso schematic。需要注意的是，具体 PDK 器件名、CDF 参数、symbol pin 顺序和工艺库路径仍需要按实际工艺环境适配。

### 6.2 自动执行 SKILL 脚本

对于已有 SKILL 工具链，virtuoso-bridge 可以作为外部调度入口：

```bash
virtuoso-bridge load create_amp.il
```

或：

```python
client.execute_skill('load("create_amp.il")')
```

更推荐的工程实践是把复杂逻辑保留在版本化的 `.il` 文件中，由 Python 负责参数生成、文件上传、调用和结果检查。这样既能复用传统 SKILL 积累，又能把实验管理、优化算法和日志系统放在 Python 侧。

### 6.3 自动调用 Spectre 仿真

Spectre 仿真链路与 SKILL bridge 相对独立。对于已经生成 netlist 的电路，`SpectreSimulator` 可用于在远程服务器上调用 Spectre，并取回结果文件。项目 README 也说明 Spectre runner 通过 SSH shell command 运行仿真，通过 rsync 等机制传输 netlist 与结果。

这适合以下场景：

- 从 Virtuoso/Maestro 导出 netlist 后批量仿真；
- 对手写或自动生成的 Spectre netlist 做快速验证；
- 多服务器或多 profile 并行运行参数扫描；
- 将 Spectre 输出作为 Python 优化器的目标函数评估结果。

实际使用时应特别关注 Cadence 环境变量、license、模型文件 include 路径、仿真工作目录和结果文件格式。若远程 shell 默认找不到 `spectre`，需要配置 `VB_CADENCE_CSHRC`。

### 6.4 自动读取仿真结果并进行优化

模拟电路自动优化的闭环可以抽象为：

```text
参数采样
  ↓
生成或修改 schematic/netlist
  ↓
运行 Spectre/OCEAN/Maestro
  ↓
读取 gain/GBW/PM/SR/power 等指标
  ↓
计算约束与目标函数
  ↓
Bayesian Optimization / TPE / gm-Id 策略更新参数
```

virtuoso-bridge 在其中承担接口层角色。它不直接替代优化算法，也不替代电路设计知识；它提供的是让优化算法能够触达 Virtuoso/SKILL/Spectre 的工程通道。

后续可以把它与以下方法结合：

- Bayesian Optimization：适合高成本黑盒优化；
- TPE：适合离散/连续混合参数空间与失败 trial 较多的场景；
- gm-Id 方法：适合建立器件级 sizing 初值和约束边界；
- rule-based check：用于过滤不合理尺寸、偏置和版图约束；
- AI Agent：用于生成 SKILL/Python 代码、解释仿真失败、整理实验报告。

### 6.5 与 AI Agent / Codex / VS Code 工作流结合

项目的 `skills/` 目录提供了面向 coding agent 的 skill 文件，包括 Virtuoso、Spectre 和 optimizer 相关入口。README 中也说明可将这些 skills 链接到用户级 Agent skills 目录，使 Agent 更容易理解 bridge 的调用方式。

在博客后续的“模拟 IC 自动化设计”系列中，可以采用如下分工：

- AI Agent：负责高层任务拆解、代码生成、错误诊断和实验记录；
- Python：负责数据结构、优化循环、结果解析和流程调度；
- SKILL：负责 Virtuoso 数据库、schematic/layout/Maestro 操作；
- Spectre/OCEAN：负责电路仿真和指标计算；
- virtuoso-bridge：负责连接 Agent/Python 与 Cadence Virtuoso。

这种结构让 Agent 不需要“看着屏幕点 GUI”，而是通过明确接口执行可复现命令。它也让设计过程更容易被记录、回放、调试和批量扩展。

## 7. 工程实践中的注意事项

第一，先验证最小链路，再做复杂自动化。初次搭建时不要一上来运行完整优化流程，应先确认 `virtuoso-bridge status`、`execute_skill("1+2")`、`windows` 等最小命令可用。

第二，区分 tunnel 问题、CIW bridge 问题和 Spectre 环境问题。三者的失败现象不同，排查路径也不同：

- tunnel 失败：优先检查 SSH、jump host、端口和 profile；
- daemon no response：优先检查 Virtuoso 是否运行、CIW 是否执行了 `load(...)`；
- Spectre not found：优先检查 PATH、`VB_CADENCE_CSHRC`、license 和 Cadence 环境初始化。

第三，复杂 SKILL 应版本化。inline SKILL 适合小测试和简单表达式；大型 schematic/layout 生成逻辑应放入 `.il` 文件，用 Git 管理，并通过 `virtuoso-bridge load` 调用。

第四，remote file 仍然在 remote file system。Maestro netlist、Spectre 输出、日志和 PSF 文件经常写在远程目录中。外部 Python 要读取这些结果时，需要明确下载、同步或使用项目提供的结果读取接口，不能假设本地路径自动存在。

第五，自动化脚本要考虑 GUI modal dialog。Virtuoso 中弹出的阻塞对话框可能导致 SKILL 通道超时。项目 CLI 提供了 `dismiss-dialog`、`list-windows`、`dismiss-window` 等 X11 辅助命令，可在合适环境下用于诊断和恢复，但这类操作应谨慎使用，避免误关闭关键窗口。

第六，不要夸大自动化接口的能力。virtuoso-bridge 提供的是连接层和若干高层封装，真正可完成的电路生成、版图辅助、仿真闭环和优化质量，仍取决于 PDK 适配、SKILL 脚本质量、仿真 testbench、指标提取方法和优化策略。

## 8. 小结：从 GUI 设计工具到 Agentic Analog Design 平台

virtuoso-bridge 的意义不在于把 Virtuoso 变成另一个 Python 库，而在于为模拟 IC 自动化设计建立一条可复现、可脚本化、可被 Agent 调用的接口链路。

传统流程中，设计者通过 GUI 操作 schematic、layout 和 ADE；自动化流程中，设计者把可重复动作表达为 Python、SKILL 和 Spectre 脚本，由 bridge 负责把这些脚本送入 Cadence 环境执行。这样，Virtuoso 继续承担工业级设计数据库和 PDK 平台的角色，Python/AI Agent 则承担搜索、调度、生成和分析的角色。

对于后续工作，virtuoso-bridge 可以作为连接“AI Agent”和“Cadence Virtuoso”的关键接口层，支撑以下方向：

- 基于 Python + SKILL 自动生成模拟电路；
- 使用 Spectre/OCEAN 自动仿真；
- 使用 Python 读取仿真结果并生成指标；
- 结合 Bayesian Optimization、TPE 和 gm-Id 方法进行参数优化；
- 让 AI Agent 参与高层设计决策、代码生成、错误诊断和报告生成；
- 逐步构建可复现的 Agentic Analog Design 平台。

第一篇文章先完成接口层的解释和搭建，后续文章可以进一步展开：如何自动生成一个最小运放 schematic，如何从 Maestro/Spectre 中提取指标，如何把 TPE 优化器接入 Virtuoso/Spectre 闭环，以及如何让 Agent 在工程约束下参与模拟电路设计。

## 参考资料

- Arcadia-1, `virtuoso-bridge-lite` GitHub 仓库：<https://github.com/Arcadia-1/virtuoso-bridge-lite>
- 项目 README：<https://github.com/Arcadia-1/virtuoso-bridge-lite/blob/main/README.md>
- Agent 使用说明 `AGENTS.md`：<https://github.com/Arcadia-1/virtuoso-bridge-lite/blob/main/AGENTS.md>
- Python/SKILL bridge 核心实现参考：`src/virtuoso_bridge/virtuoso/basic/bridge.py` 与 `src/virtuoso_bridge/virtuoso/basic/resources/ramic_bridge.il`
