---
title: "Lab 4"
date: 2026-06-25
draft: false
tags: ["Analog IC", "Blog"]
categories: ["Notes"]
---

**模拟电路自动化设计工程报告**  
**——以全差分两级运放优化算法为** **例**  
**1. 项目背景**  
模拟集成电路设计具有强非线性、多目标、多约束和高仿真成本等特点。传统模拟电路设计通常依赖设计者经验，通过手动调整器件尺寸、偏置电流、补偿参数和版图约束来满足性能指标。该过程不仅耗时，而且对设计者经验依赖较强。  
   
 本工程 AutoDesign2.0 面向模拟 CMOS 电路自动化设计，目标是在 Cadence Virtuoso、Spectre/OCEAN、Python 优化算法和 AI Agent 辅助决策之间建立自动闭环。当前工程已经完成从工艺库配置、拓扑封装、指标提取、优化搜索到结果报告生成的完整流程，并以 TSMC180 工艺下的全差分两级运放 DiffAmp  
   
 作为复杂电路验证对象。  
   
 目标电路为全差分两级运放，包含 folded-cascode 第一级、common-source 第二级、双 CMFB 以及 RC Miller 补偿网络。设计指标如下：  
   
 | **指标** |  **目标** |  
   
 | 直流增益 | > 80 dB |  
   
 | 单位增益带宽 GBW | > 50 MHz |  
   
 | 负载电容 CL | 5 pF |  
   
 | 相位裕度 PM | > 60° |  
   
 | 压摆率 SR | > 100 V/µs |  
   
 | 电源电压 VDD | 2.0 V |  
**2. AutoDesign2.0 工程架构概述**  
AutoDesign2.0的核心设计思想是将“人为设计决策”和“底层仿真执行”解耦。工程中 main.py 被设计为唯一人工控制入口，用于集中配置工艺库、电路拓扑、测量指标、优化目标、搜索空间、seeds、优化调度和结果报告；底层模块则分别负责 PDK 生成、拓扑解析、OCEAN 仿真、指标提取、优化算法和结果绘图。  
   
 整体流程如下：  
   
 main.py 顶层配置  
   
     ↓  
   
 PDK auto-generation  
   
     ↓  
   
 Topology Package 生成 / 加载  
   
     ↓  
   
 Declarative Metrics 配置  
   
     ↓  
   
 TPE / 多阶段优化  
   
     ↓  
   
 OCEAN / Spectre 仿真  
   
     ↓  
   
 metrics 提取与 smooth loss 计算  
   
     ↓  
   
 trial history / summary / diagnosis  
   
     ↓  
   
 最终候选筛选与 report 生成  
   
    
**3. 优化问题建模**  
模拟电路优化本质上不是简单的单目标数值最小化问题，而是一个带有强约束和多目标折中的复杂工程优化问题。以当前 DiffAmp 为例，优化变量包括 MOS 器件尺寸、偏置相关参数、补偿电阻 Rc、补偿电容 Cc 等。优化目标不仅是使电路满足增益、带宽、相位裕度和压摆率等指标，还要避免过设计、过大器件宽度、过高功耗以及不合理版图实现。  
   
 因此，本工程将优化问题划分为两层：  
**3.1 约束层**  
约束层用于判断设计是否满足基本功能和规格要求：  
   
 gain ≥ 80 dB  
   
 GBW ≥ 50 MHz  
   
 PM ≥ 60°  
   
 SR ≥ 100 V/µs  
   
 Vout_cm 接近目标共模电压  
   
 power 不超过设定上限  
   
 器件尺寸满足合法范围  
   
 关键 MOS 工作区满足要求  
   
    
**3.2 成本层**  
成本层用于在满足基本指标之后进一步筛选工程上更优的设计：  
   
 minimize power  
   
 minimize total_width  
   
 minimize total_gate_area  
   
 minimize max_device_width  
   
 minimize max_W/L  
   
 minimize GBW excess  
   
 minimize Cc  
   
 minimize layout penalty  
   
    
   
 这种“先可行、再压缩成本”的思想比单纯追求最低 smooth loss 更符合模拟电路设计流程。  
**4. TPE 贝叶斯优化算法**  
当前工程采用基于 Optuna/TPE 的贝叶斯优化方法。TPE，即 Tree-structured Parzen Estimator，是一种适用于黑盒函数优化的采样算法。对于模拟电路而言，每一次参数评估都需要调用 Spectre/OCEAN 仿真，因此目标函数不可导、代价高且可能存在仿真失败。TPE 正适合此类场景。  
**4.1 TPE 的基本思想**  
传统随机搜索不利用历史信息，而 TPE 会根据历史 trial 结果建立概率模型，将参数空间分为“较优区域”和“较差区域”，并优先采样更可能产生较优结果的参数组合。  
   
 在本工程中，单次 trial 的流程为：  
   
 TPE 生成候选参数  
   
     ↓  
   
 参数绑定到 topology package / netlist / OCEAN  
   
     ↓  
   
 Spectre 仿真  
   
     ↓  
   
 OCEAN 提取 gain、GBW、PM、SR、power 等指标  
   
     ↓  
   
 Python 计算 smooth loss  
   
     ↓  
   
 TPE 根据结果更新采样分布  
   
    
**4.2 TPE 在模拟电路中的优势**  
TPE 相比普通网格扫描或随机搜索具有以下优势：  
1. **适合高成本黑盒优化  
   
  **每个候选点都需要真实 SPICE 仿真，TPE 能利用已有结果减少无效搜索。  
2. **适合非线性、多峰问题  
   
  **模拟电路性能对尺寸和偏置高度非线性，TPE 不要求目标函数连续或可导。  
3. **支持复杂搜索空间  
   
  **可以同时处理连续变量、离散变量、log-space 变量和条件变量。  
4. **可与 seeds 机制结合  
   
  **可将人工验证点、gm/Id 估计点或历史可行点 enqueue 到优化过程，提高初期搜索效率。  
**5. Smooth Loss 设计**  
在模拟电路优化中，如果只使用 pass/fail 判断，会导致优化器无法区分不同失败程度。例如，一个增益只差 1 dB 的设计和一个完全不工作的设计都可能被标记为 fail，这会降低优化效率。  
   
 因此，本工程引入 smooth loss，将每个指标的 violation 转化为连续惩罚。其主要作用不是提供梯度，而是为 TPE 提供更细致的 trial 排序。  
**5.1 单边约束惩罚**  
对于下限指标，例如：  
   
 gain ≥ gain_min  
   
 GBW ≥ GBW_min  
   
 PM ≥ PM_min  
   
 SR ≥ SR_min  
   
    
   
 可以定义平滑惩罚：  
   
 loss_gain = softplus((gain_min - gain) / scale_gain)  
   
    
   
 当指标满足要求时，惩罚接近 0；当指标不足时，惩罚随不足程度连续增加。  
**5.2 共模误差惩罚**  
对于输出共模电压：  
   
 Vout_cm ≈ Vcm_target  
   
    
   
 使用目标偏差惩罚：  
   
 loss_cm = softplus((abs(Vout_cm - Vcm_target) - tolerance) / tolerance)  
   
    
   
 该项用于防止全差分运放输出共模漂移或 CMFB 失效。  
**5.3 过设计惩罚**  
在多次优化后发现，部分可行解虽然满足指标，但存在 GBW 远高于目标、MOS 宽度过大等问题。因此本工程进一步引入过设计惩罚：  
   
 GBW_min ≤ GBW ≤ GBW_max_useful  
   
    
   
 如果 GBW 过高，则加入：  
   
 loss_gbw_excess = softplus(log(GBW / GBW_max_useful))  
   
    
   
 这样可以避免优化器通过增大电流和器件尺寸获得远超需求的带宽。  
**5.4 尺寸与版图友好惩罚**  
为了使优化结果更接近真实版图可实现设计，成本函数中加入以下 derived metrics：  
   
 total_width      = Σ W_i  
   
 total_gate_area  = Σ W_i · L_i  
   
 max_device_width = max(W_i)  
   
 max_W_over_L     = max(W_i / L_i)  
   
    
   
 对应惩罚项包括：  
   
 loss_width = log(total_width / total_width_ref)  
   
 loss_area  = log(total_gate_area / area_ref)  
   
 loss_maxW  = softplus(log(max_device_width / max_device_width_limit))  
   
 loss_WL    = softplus(log(max_WL / max_WL_limit))  
   
    
   
 这些惩罚项使优化器不仅追求性能达标，也倾向于选择尺寸更合理、版图更友好的候选点。  
**6. 两阶段优化策略**  
单阶段 TPE 优化容易出现“找到可行解但不够工程最优”的问题。因此工程中引入两阶段优化策略。  
**6.1 Phase 1：Feasibility Search**  
第一阶段目标是快速找到满足基本性能约束的可行解。该阶段的 loss 主要由指标 violation 构成，包括：  
   
 gain violation  
   
 GBW violation  
   
 PM violation  
   
 SR violation  
   
 output CM violation  
   
 power upper-bound violation  
   
 basic size legality violation  
   
    
   
 该阶段允许一定程度的过设计，因为主要目标是找到 feasible region。  
**6.2 Phase 2：Cost Compression**  
第二阶段在可行解附近继续优化，目标从“满足指标”转向“降低工程成本”。该阶段重点优化：  
   
 power  
   
 total_width  
   
 gate_area  
   
 max_device_width  
   
 max_W/L  
   
 GBW excess  
   
 Cc  
   
 layout penalty  
   
    
   
 第二阶段的候选点可以来自 Phase 1 的可行解，优化空间也可以围绕这些可行解自适应收缩。  
   
 该策略更接近真实模拟电路设计过程：  
   
 先让电路工作  
   
 再让性能达标  
   
 最后降低功耗、面积和版图代价  
   
    
**7. Seeds 机制**  
为了提高 TPE 初始阶段的搜索效率，工程支持 enqueued seeds 机制。Seeds 不是由随机采样得到，而是基于已有设计经验、人工验证点或 gm/Id 方法生成。  
   
 当前推荐的 seeds 类型包括：  
   
 5. **validated_initial  
   
  **已经仿真验证过的初始点，用于保证优化过程从一个可工作区域出发。  
   
 6. **low_power  
   
  **偏向较低电流和较小器件尺寸，用于探索低功耗区域。  
   
 7. **balanced  
   
  **在增益、带宽、功耗和尺寸之间折中，用作常规初始点。  
   
 8. **low_area  
   
  **偏向较小总宽度和较小栅面积，用于探索版图紧凑方案。  
   
 9. **high_margin  
   
  **偏向较高增益和较高相位裕度，用于探索鲁棒性更强的设计。  
   
 10. **gm/Id seed hook  
   
  **后续可以基于 gm/Id LUT 自动生成物理上更合理的初始点。当前若 gm/Id seed 尚未完全实现，应保留 hook，而不是伪造结果。  
   
 Seeds 机制的意义在于将模拟电路设计经验引入优化初期，避免 TPE 完全依赖随机启动。  
**8. 搜索空间优化**  
搜索空间设计直接影响优化结果。如果搜索空间允许过大的 MOS 宽度或过宽的电流比例范围，优化器可能通过“暴力增大尺寸”获得可行解。因此，本工程引入 layout-friendly search space preset。  
   
 该 preset 主要特点包括：  
   
 对 widths、currents、Cc、Rc 使用 log-space 搜索  
   
 限制二级放大器和负载器件的过大宽度  
   
 限制 max_device_width  
   
 限制 max_W/L  
   
 允许在 main.py 中覆盖 topology package 自动生成的 search space  
   
    
   
 例如：  
   
 SEARCH_SPACE_PRESET = "diffamp_layout_friendly"  
   
    
   
 SEARCH_SPACE_OVERRIDES = {  
   
     "w_stage2": {"min_factor": 0.4, "max_factor": 1.2, "scale": "log"},  
   
     "w_load2": {"min_factor": 0.4, "max_factor": 1.3, "scale": "log"},  
   
     "cc": {"min_factor": 0.5, "max_factor": 1.8, "scale": "log"},  
   
     "rc": {"min_factor": 0.3, "max_factor": 3.0, "scale": "log"}  
   
 }  
   
    
   
 这样做可以减少不现实候选点数量，提高优化效率和结果质量。  
**9. Feasible-first 最终候选选择**  
传统做法通常直接选择 raw loss 最小的 trial 作为 best design。但在模拟电路中，raw loss 最小不一定意味着工程最优。例如，一个设计可能因为 GBW 极高而得到较好指标，但其功耗和面积明显过大。  
   
 因此，本工程采用 feasible-first final ranking：  
   
 11. 先筛选满足全部硬约束的 feasible designs；  
   
 12. 再按照工程成本排序；  
   
 13. 输出多个候选，而不是单一 best。  
   
 推荐输出包括：  
   
 | **候选类型** |  **含义** |  
   
 | best_by_loss | 原始 loss 最小 |  
   
 | best_feasible_low_power | 可行解中功耗最低 |  
   
 | best_feasible_low_area | 可行解中面积最小 |  
   
 | best_feasible_layout_friendly | 可行解中尺寸和版图代价最合理 |  
   
 | best_feasible_balanced | 综合性能、功耗、面积和裕量最平衡 |  
   
 这种方法更符合模拟电路设计实际，因为工程上往往需要在多个 Pareto 候选中做最终选择。  
**10. 总结**  
AutoDesign2.0 已经从早期的单电路自动调参工具，发展为具有 PDK 自动生成、拓扑包、声明式 metrics、OCEAN/Spectre 后端、TPE 优化、smooth loss、结果绘图和 Agent 诊断能力的模拟电路自动化设计平台。  
   
 在优化算法方面，当前工程的核心特点是：  
   
 TPE 贝叶斯优化  
- smooth loss  
- layout-friendly search space  
- two-phase optimization  
- overdesign penalty  
- seeds enqueue  
- feasible-first final ranking  
- agent diagnosis  
   
 该方法相比单纯 TPE 或随机搜索更适合复杂模拟电路设计。它不仅能提高可行解数量，还能进一步约束功耗、面积、器件尺寸和过设计问题。  
   
 不过，对于复杂模拟电路而言，单纯依赖数值优化仍然不足。后续更优方向是将 AI Agent 作为顶层设计决策者，使其基于仿真历史和诊断结果动态调整搜索空间、目标函数、约束和 seeds。最终目标不是简单找到满足指标的设计，而是找到满足指标、功耗合理、面积合理、版图可实现、跨 corner 可靠的工程最优设计。  
   
    
   
    
   
    
   
    
   
    
   
    
   
    
   
    
