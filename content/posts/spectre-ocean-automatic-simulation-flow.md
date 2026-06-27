---
title: "三、基于 Spectre/OCEAN 的模拟电路自动仿真流程"
date: 2026-06-27
draft: false
categories: ["模拟IC自动化设计"]
tags: ["模拟IC", "Cadence Virtuoso", "Spectre", "OCEAN", "EDA自动化", "仿真流程", "AI Agent", "IC自动化设计", "Virtuoso"]
series: ["模拟IC自动化设计"]
weight: 3
---

# 基于 Spectre/OCEAN 的模拟电路自动仿真流程

## 1. 背景：为什么需要自动仿真流程

前两篇文章分别讨论了两个基础问题：如何通过 virtuoso-bridge 让 Python / AI Agent 连接 Cadence Virtuoso，以及如何使用 SKILL 自动生成模拟电路原理图。完成这两步之后，自动化流程已经可以把结构化电路描述落地为 Virtuoso schematic。但对模拟 IC 设计而言，原理图只是起点，真正决定电路是否可用的是仿真结果。

传统手动仿真流程通常依赖 ADE 或 Maestro GUI：修改参数、重新 netlist、点击 run、查看波形、手动读取 gain、GBW、PM、SR、power 等指标。这种方式适合单次设计分析，但不适合多轮自动优化。原因很直接：

- 每次修改参数后都需要人工重新 netlist 和 run；
- 难以批量评估大量候选电路；
- 难以与 TPE、Bayesian Optimization、gm-Id sizing 等算法连接；
- 结果目录容易被覆盖或混在一起；
- 不利于稳定提取性能指标；
- 不适合 AI Agent 或 Python optimizer 进行多轮迭代。

自动化仿真的目标，是把一次仿真封装为稳定的函数调用：

```text
设计参数
   ↓
自动更新 schematic / testbench
   ↓
自动 netlist
   ↓
自动运行 Spectre
   ↓
保存仿真结果
   ↓
Python 提取指标
   ↓
优化器生成下一组参数
```

在这个流程中，Spectre 是底层晶体管级仿真器，OCEAN 是 Cadence 环境中的脚本化仿真与结果访问接口，Python 负责顶层任务调度、参数管理和结果目录组织。本文关注的是第三篇中的核心问题：原理图自动生成之后，如何构建可重复、可批量执行、可接入优化闭环的 Spectre/OCEAN 自动仿真流程。

## 2. Spectre 与 OCEAN 在 Virtuoso 流程中的角色

### 2.1 Spectre：底层电路仿真器

Spectre 负责执行晶体管级电路仿真。它读取 netlist、model include、design variables、analysis 设置和仿真选项，然后输出日志、raw/psf 数据、工作点信息和波形数据。

在自动化流程中，Spectre 通常关注以下问题：

- netlist 是否语法正确；
- model file 和 section 是否正确；
- design variables 是否完整；
- DC operating point 是否收敛；
- AC、Transient、STB 等 analysis 是否正常完成；
- raw/psf/psfascii 结果是否按预期写入目录；
- `spectre.out` 中是否存在 error、fatal 或关键 warning。

Spectre 本身并不关心优化器，也不负责决定下一组参数。它只回答一个问题：给定电路和仿真设置后，电路响应是什么。

### 2.2 OCEAN：脚本化仿真控制接口

OCEAN 可以理解为 Virtuoso/ADE/Spectre 流程的脚本化接口。它既可以配置仿真器、design、analysis 和 design variables，也可以在仿真后打开结果并计算表达式。

典型 OCEAN 脚本可以负责：

- 设置仿真器为 Spectre；
- 打开 design 或 testbench；
- 设置仿真结果目录；
- 设置 design variables；
- 配置 dc、ac、tran、stb 等 analyses；
- 设置需要保存的节点、电流和 OP 信息；
- 执行仿真；
- 打开结果目录；
- 计算部分性能指标并写入文本文件。

在不同工程中，OCEAN 可以承担的范围不同。有些流程使用 OCEAN 完成 netlist + run + measurement；有些流程则直接调用 Spectre 运行 netlist，再使用 OCEAN 读取 Spectre 输出并计算指标。两种方式都可以成立，关键是职责边界要清楚，结果目录要可追踪。

### 2.3 Python：顶层任务调度器

Python 适合做自动化系统中的顶层调度：

- 生成每一轮候选设计参数；
- 生成或修改 OCEAN 脚本；
- 创建独立 run directory；
- 调用 `ocean` 或 `spectre`；
- 收集 return code、log、raw/psf 和 performance 文件；
- 将仿真结果转化为结构化 metrics；
- 将 metrics 交给 optimizer 计算 loss。

一个合理的职责划分如下：

| 模块 | 主要职责 |
|---|---|
| Spectre | 执行晶体管级电路仿真，生成 raw/psf/日志等结果 |
| OCEAN | 脚本化控制 ADE / 仿真设置 / 仿真运行 / 结果访问 |
| Python | 生成任务、修改参数、调用脚本、管理目录、组织优化循环 |
| SKILL | 操作 Virtuoso 数据库，例如 schematic/testbench 生成 |
| Optimizer | 根据性能指标选择下一组设计参数 |

## 3. 从原理图到仿真结果的自动化链路

### 3.1 schematic 与 testbench

自动仿真首先需要明确被测电路和 testbench 的边界。DUT schematic 描述电路本体，testbench schematic 描述输入激励、电源、偏置、负载、测量节点和仿真环境。

在模拟电路自动化中，不建议把所有仿真设置散落在 GUI 状态里。更稳妥的做法是让 testbench、design variables、analysis 和结果目录都能被脚本明确控制。这样每次 trial 的输入是可记录的，仿真失败时也能复现。

### 3.2 netlist 生成

Spectre 运行的是 netlist，不是 schematic 图形对象。自动化流程通常有两种方式：

- 通过 Virtuoso/ADE/OCEAN 从 schematic/testbench 生成 netlist；
- 使用参数化 Spectre netlist 模板，由 Python 渲染每一轮参数后直接运行 Spectre。

第一种方式更贴近 OA schematic 和 PDK pcell，适合 sign-off 或与 Virtuoso 数据库强绑定的流程；第二种方式启动开销较小，适合优化内循环。实际工程中可以组合使用：优化内循环使用参数化 netlist 加速，关键候选点再回到真实 OA testbench 做验证。

无论采用哪种方式，都需要保证 model include、model section、器件参数、节点命名和 testbench 设置一致。

### 3.3 OCEAN 脚本配置

OCEAN 脚本可以由 Python 生成，也可以使用模板替换参数。一个简化示例如下：

```lisp
simulator('spectre)
design("myLib" "ota_tb" "schematic")
resultsDir("./results/run_001")

desVar("w_in" "10u")
desVar("l_in" "180n")
desVar("cc" "1p")

analysis('dc ?saveOppoint t)
analysis('ac ?start "1" ?stop "1G" ?dec 20)
analysis('tran ?stop "1u")

save('v "/vout")
run()
```

这只是示意代码。真实工程中需要根据 PDK、testbench、ADE 状态、仿真器版本和测量需求调整 OCEAN 语法。对于复杂项目，建议把 OCEAN 脚本拆成“仿真设置”和“结果提取”两个阶段，便于定位错误。

### 3.4 Spectre 仿真执行

如果直接运行 netlist，可以采用类似命令：

```bash
spectre input.scs +log spectre.out -format psfascii -raw psf
```

其中：

- `input.scs` 是本轮仿真 netlist；
- `spectre.out` 是本轮仿真日志；
- `-raw psf` 指定结果目录；
- `-format psfascii` 在某些流程中便于后续文本化读取。

是否使用 `psfascii` 取决于结果读取脚本和数据规模。ASCII 结果更容易调试，但通常比 binary PSF 更占空间；大规模仿真时应权衡速度、空间和可读性。

### 3.5 结果文件保存与管理

自动仿真必须把每次 trial 的输入、日志、结果和指标保存到独立目录。否则，一旦某次仿真失败，很难判断失败是由参数、netlist、license、model path 还是结果覆盖造成的。

通用链路可以抽象为：

```text
x → netlist(x) → Spectre → waveform / psf → metrics
```

其中 `x` 是设计参数，`metrics` 是结构化性能指标。更形式化地看：

```text
m = Simulate(x)
m_i = f_i(x), i = 1,2,...,N
```

每个 `f_i` 对应一个性能指标提取过程，例如 DC gain、GBW、PM、slew rate 或 power。

## 4. 自动仿真的工程目录组织

自动仿真应避免把所有中间文件写入同一个目录。一个通用结构如下：

```text
results/
  trial_0001/
    run.ocn
    input.scs
    spectre.out
    psf/
    metrics.json
    performance.txt
  trial_0002/
    run.ocn
    input.scs
    spectre.out
    psf/
    metrics.json
    performance.txt
```

这种组织方式有几个优点：

- 每个 trial 独立保存，不会互相覆盖；
- 失败样本可以单独复现；
- 可以快速定位 netlist、log、raw data 和 metric 是否一致；
- 便于筛选 best design；
- 便于生成 `history.jsonl`、`summary.json` 和报告；
- 便于后续做缓存、恢复和断点续跑。

在工程实践中，我更倾向于让 Python 创建 run root，再为每个候选点创建独立 trial 目录。Spectre/OCEAN 只在当前 trial 目录内读写文件，减少路径混乱。

## 5. 常见仿真类型的自动化设置

### 5.1 DC 工作点仿真

DC 工作点仿真用于判断电路是否具备基本偏置条件。自动化流程中，DC 仿真通常用于检查：

- MOS 是否工作在合理区域；
- 偏置电流是否正确；
- 输出共模是否在可接受范围；
- 是否存在浮空节点；
- 是否出现不收敛；
- 电源电流和静态功耗是否异常。

对于优化流程，DC OP 是第一道过滤器。如果 DC 工作点已经失败，后续 AC 或 transient 指标通常没有意义。

### 5.2 AC 小信号仿真

AC 仿真通常用于提取：

- DC gain；
- 单位增益带宽 GBW；
- 相位裕度 PM；
- 主极点和非主极点行为；
- 差分增益或共模响应。

需要注意的是，PM 的提取方法依赖 testbench 和环路打开方式。对于简单闭环或开环 OTA，可能通过差分输出传递函数估计；对于复杂反馈环路或 CMFB，可能需要专门的 stb testbench。文章和脚本中都不应把某一种 PM 提取方式写成唯一正确方法。

### 5.3 Transient 瞬态仿真

Transient 仿真用于观察大信号动态行为，例如：

- slew rate；
- settling time；
- 输出摆幅；
- step response；
- startup 或 large-signal recovery。

自动提取 slew rate 时，需要明确时间窗口、输入激励、输出节点和导数计算方式。如果时间窗口过宽，可能把噪声或后续振铃误判为最大斜率；如果时间窗口过窄，可能错过真正的上升/下降沿。

### 5.4 稳定性与环路分析

STB 或环路稳定性分析常用于：

- loop gain；
- phase margin；
- gain margin；
- CMFB 稳定性；
- 多环路结构的局部稳定性分析。

这类仿真强依赖 testbench 结构和环路切断方式。自动化脚本可以统一运行流程，但环路注入点、保存信号和指标公式仍需要设计者基于电路结构审查。

## 6. Python + OCEAN 的协同方式

### 6.1 Python 生成仿真任务

Python 应把每次仿真视为一个独立任务。任务输入包括：

- 当前候选参数；
- netlist 或 schematic/testbench 引用；
- OCEAN 模板；
- model file 和 model section；
- analysis 设置；
- run directory；
- timeout 和错误处理策略。

### 6.2 Python 写入参数

参数写入可以发生在三个位置：

- 写入 schematic/testbench 的 design variables；
- 写入 OCEAN 脚本中的 `desVar(...)`；
- 写入参数化 Spectre netlist 的 `parameters` 行。

三种方式各有适用场景。schematic 回写更贴近 Virtuoso 数据库；OCEAN `desVar` 适合 ADE 风格流程；netlist 模板渲染适合快速优化内循环。无论采用哪种方式，都要确保参数单位、字符串格式和 PDK CDF 字段一致。

### 6.3 Python 调用 OCEAN 或 Spectre

简化后的 Python 调度示例如下：

```python
from pathlib import Path
import subprocess

def run_simulation(params, run_dir):
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    ocean_script = generate_ocean_script(params, run_dir)
    script_path = run_dir / "run.ocn"
    script_path.write_text(ocean_script, encoding="utf-8")

    cmd = ["ocean", "-nograph", "-restore", str(script_path)]
    result = subprocess.run(
        cmd,
        cwd=run_dir,
        capture_output=True,
        text=True,
        check=False,
    )

    return result.returncode == 0
```

其中：

- `params` 对应当前候选设计参数；
- `generate_ocean_script()` 将参数写入 OCEAN；
- 每次仿真使用独立 `run_dir`；
- 后续 Python 从结果目录中读取波形、日志或指标文件。

这个示例只展示调度思想。实际工程中还需要加入 timeout、日志保存、结果存在性检查、metric 有效性检查和异常分类。

### 6.4 Python 管理结果目录

Python 不应只关心命令是否返回 0。一次仿真任务至少应记录：

- return code；
- stdout/stderr；
- `spectre.out`；
- netlist 文件；
- raw/psf 结果目录；
- OCEAN 脚本；
- performance 或 metrics 文件；
- 失败原因分类。

在批量优化时，建议把每次 trial 的摘要写入行式日志，例如 `history.jsonl` 或 CSV。这样即使中途停止，也能恢复已经完成的实验记录。

## 7. 一个简化的自动仿真流程示例

下面给出一个抽象流程，说明如何把参数、netlist、Spectre 和 OCEAN 连接起来。示例经过简化，不对应任何真实工程实现。

```python
from pathlib import Path
import json
import subprocess

def render_netlist(template, params):
    text = template
    for name, value in params.items():
        text = text.replace(f"{{{{{name}}}}}", str(value))
    return text

def run_trial(trial_id, params, template_text, root):
    trial_dir = Path(root) / f"trial_{trial_id:04d}"
    trial_dir.mkdir(parents=True, exist_ok=True)

    netlist = trial_dir / "input.scs"
    log_file = trial_dir / "spectre.out"
    raw_dir = trial_dir / "psf"

    netlist.write_text(render_netlist(template_text, params), encoding="utf-8")

    cmd = [
        "spectre",
        netlist.name,
        "+log",
        log_file.name,
        "-raw",
        raw_dir.name,
    ]
    completed = subprocess.run(
        cmd,
        cwd=trial_dir,
        capture_output=True,
        text=True,
        check=False,
    )

    status = {
        "trial": trial_id,
        "returncode": completed.returncode,
        "ok": completed.returncode == 0 and raw_dir.exists(),
    }
    (trial_dir / "status.json").write_text(
        json.dumps(status, indent=2),
        encoding="utf-8",
    )
    return status
```

这类流程还需要后处理步骤，例如生成 OCEAN extraction script，打开结果目录，计算指标，并写入 `metrics.json` 或 `performance.txt`。关键思想是：每个 trial 的输入、执行日志、原始结果和指标必须能相互对应。

## 8. 在模拟 IC 优化闭环中的作用

自动仿真流程的目标不是单次运行，而是成为优化器中的评价函数：

```text
score = Evaluate(Simulate(x))
```

其中：

- `Simulate(x)` 负责根据参数 `x` 生成或更新电路，运行 Spectre/OCEAN，并获得仿真结果；
- `Evaluate()` 负责把仿真结果转换为指标、约束状态和 loss；
- optimizer 根据 loss 选择新的 `x`。

优化闭环可以写成：

```text
x_k → simulation → metrics_k → loss_k → x_{k+1}
```

这要求仿真 backend 不只是“能跑”，还必须具备工程可靠性：失败可诊断、结果可追踪、指标可验证、目录可恢复。否则优化器会把仿真异常误认为电路性能差，或者把无效数据用于下一轮采样。

## 9. 工程实践中的注意事项

### 9.1 仿真成功不能只看 return code

自动化流程必须同时捕获：

```text
return code + log file + result existence + metric validity
```

命令返回 0 只能说明进程正常退出，不代表指标一定有效。还需要确认 raw/psf 目录存在、OCEAN 能打开结果、关键波形已保存、指标不是 `nan` 或 `inf`。

### 9.2 netlist 失败要尽早停止

常见 netlist 问题包括：

- schematic 与 symbol 端口不一致；
- design variable 未定义；
- 器件 CDF 参数缺失；
- PDK model path 或 model section 错误；
- include 文件路径错误；
- 节点名或 terminal name 不一致。

这类错误通常不应进入 optimizer 评分阶段，而应作为 flow failure 直接上报。

### 9.3 仿真不收敛要分类处理

不收敛可能来自电路本身，也可能来自仿真设置。自动化系统应至少区分：

- DC operating point 失败；
- transient step 太激进；
- 初始条件不合理；
- 电路浮空；
- 偏置点超出合理范围；
- 仿真器选项过于严格或过于宽松。

对于优化流程，某些不收敛可以记为无效 trial，但应保留日志，方便判断是参数空间问题还是 testbench 问题。

### 9.4 结果目录不能互相覆盖

多次仿真写入同一目录会导致最难排查的问题：netlist 来自 trial A，raw data 来自 trial B，metrics 来自 trial C。每个 trial 必须独立保存，并在上层摘要中记录参数、状态和指标。

### 9.5 保存信号必须服务指标提取

如果 OCEAN 或 Spectre 没有保存某个节点、电流或 OP 信息，后续 Python 或 OCEAN 表达式就无法提取指标。指标定义应反向约束 save 列表：需要计算 power，就要保存电源电流；需要计算 slew rate，就要保存对应 transient 输出；需要 gm/Id，就要保存或访问 operating point。

### 9.6 PSF 格式要与读取脚本匹配

不同工具和脚本对 PSF、PSF XL、psfascii 或导出文本的支持不同。自动化流程应明确约定结果格式，并在启动阶段做最小 smoke test，确认读取脚本能打开该格式。

### 9.7 license 和环境初始化要显式检查

在远程 EDA 服务器上，`spectre`、`ocean`、model file 和 license 都可能依赖 shell 环境。建议在正式优化前增加环境检查：

- `spectre` 是否可执行；
- `ocean -nograph` 是否能启动；
- model file 是否存在；
- license 是否可用；
- 结果目录是否可写。

### 9.8 checkpoint 比事后补救更重要

一个稳健的自动化流程应在关键阶段设置 checkpoint：

- PDK/model 检查；
- netlist smoke；
- baseline 仿真；
- metric extraction；
- optimizer trial；
- report 或 best design 验证。

每个 checkpoint 都应给出清晰诊断。不要让错误一直传播到最后才表现为“优化器没有找到好结果”。

## 10. 小结

基于 Spectre/OCEAN 的自动仿真流程，是模拟 IC 自动化设计从“能生成电路”走向“能评价电路”的关键环节。Spectre 负责晶体管级仿真，OCEAN 负责脚本化控制和结果访问，Python 负责参数调度、目录管理和优化循环，SKILL 则负责 Virtuoso 数据库和 testbench 的自动化操作。

从自动化设计角度看，一次仿真不应只是一次命令执行，而应是一个可审计的任务：输入参数明确，netlist 可追踪，日志可检查，raw/psf 可读取，metrics 可验证，失败原因可分类。只有这样，仿真流程才能稳定地嵌入优化器，形成真正的模拟电路自动设计闭环。

本文完成了自动仿真流程的构建。下一步，自动化系统需要从 Spectre 生成的 PSF、ASCII 或日志文件中提取可量化的性能指标，例如 Gain、GBW、PM、SR 和功耗。只有将波形数据转化为结构化指标，优化器才能真正参与电路设计。因此，下一篇文章将介绍如何使用 Python 读取仿真结果并构建性能指标提取模块。
