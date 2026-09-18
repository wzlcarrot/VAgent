# Harness 工程说明

> 一句话：**`Agent = Model + Harness`**。模型负责"聪明"，Harness 负责让它**可控、可观测、可复现、可评测**。

---

## 一、Harness 是什么

`harness` 原意是马具（缰绳、鞍、套具）——把马拴到车上、驾驭它的那套东西。

- **模型 = 一匹野马**：有力量，但行为不可预测（同一问题今天答 A、明天答 B）
- **Harness = 马具**：让它能拉车、能控方向、能记录、能体检

**定义**：Agent Harness = 包在模型外面、把不可预测的黑盒变成可靠产品的**全部工程设施**。

它解决四件事：

| 目标 | 手段 |
|------|------|
| **能跑** | 执行引擎（Agent Loop）、工具、上下文、会话 |
| **别乱跑** | 权限、护栏、审批、超时、熔断、步数上限 |
| **看得见** | Trace、日志、指标、artifact |
| **能复现/验证** | Replay、Checkpoint、评测集、回归门禁 |

---

## 二、Agent = Model + Harness

```
Agent
├── Model           智能：理解、推理、决策的"内容"
└── Harness         其余全部工程：
    ├── 执行引擎     Agent Loop（决策→调工具→观察→终止）
    ├── 能力         Tools
    ├── 上下文/记忆   Context / Memory
    ├── 控制         权限 / 护栏 / 审批 / 熔断
    ├── 观测         Trace / 指标 / Artifact
    └── 评测         Golden / Replay / 回归
```

> 判据：**凡是"不是模型本身、但让 Agent 能跑/别乱跑/看得见/能复现"的代码 → 都在 Harness 里。**

---

## 三、VAgent 的 Harness 实现

### 1. 执行引擎（能跑）
| 模块 | 作用 |
|------|------|
| `app/harness/agent_loop.py` | 通用 ReAct 执行引擎（`decide/execute/observe` 回调 + typed stop_reason + nudge + 预算） |
| `app/harness/hooks.py` | 生命周期钩子（可拦截/观察） |

### 2. 控制（别乱跑）
| 模块 | 作用 |
|------|------|
| `app/harness/tool_governor.py` | 工具治理：**deny by default** + 限流 + 超时 + 结果投影 + trace + artifact |
| `app/harness/tool_policy.py` | 声明式策略：allow/forbidden/ask + 限流/超时/截断 + **参数级类型化谓词**（gte/lte/regex） |
| `policies/tool_policy.json` | 策略即数据（改规则不动代码） |
| `app/harness/guardrails.py` | 输入注入检测 + 域外拦截 + 输出改写（规则先行） |
| `app/harness/hitl_approval.py` | 人工审批：ask → 前端确认 → 续跑；**审批缓存**（批准一次，同会话免重复问） |
| `app/tools/llm_circuit.py` | LLM 熔断 |
| `app/agents/react_guard.py` | 重复工具调用检测 |
| `app/harness/tool_projection.py` | 结果投影 / 租户参数注入 |

### 3. 观测（看得见）
| 模块 | 作用 |
|------|------|
| `app/harness/run_trace.py` | 每步事件打点（`run_artifacts` 表） |
| `app/harness/tool_progress.py` / `llm_progress.py` | 工具/LLM 进度事件（SSE） |
| `scripts/replay_trace.py` | 轨迹回放 |
| `scripts/metrics_dashboard.py` | 指标看板 |

### 4. 复现（能重跑）
| 模块 | 作用 |
|------|------|
| `app/harness/llm_replay.py` | 固定 LLM 输出，保证 CI 确定性（demo/replay 模式） |
| `app/harness/checkpoint.py` | 工作流断点续跑（`workflow_checkpoints` 表） |

### 5. 评测（能验证）
| 资产 | 作用 |
|------|------|
| `scripts/eval_react_metrics.py` | 路由 / 工具选择 / 步数 |
| `scripts/eval_semantic_retry.py` | 语义重试 ablation |
| `scripts/eval_stop_on_sufficient.py` | 省步 ablation |
| `scripts/eval_memory_supersede.py` / `eval_memory_judge.py` | 记忆取代/冲突 |
| `scripts/eval_retrieval_metrics.py` | 检索 recall@k / MRR |
| `app/harness/sse_assert.py` | SSE 回归断言 |
| `app/harness/live_regression.py` | 真实 LLM 回归 |
| `app/harness/weekly_golden.py` | 用户反馈 → 本周 golden（评测集会生长） |
| `fixtures/*.jsonl` + `tests/*` | 评测集 + 门禁 |

---

## 四、设计原则

1. **代码管边界、模型管语义**：流程、权限、兜底用代码；理解、判断、生成用模型。
2. **deny by default**：工具默认不可用，显式放行。
3. **可回退**：`harness_enabled` 一关，整体短路。
4. **可复现**：LLM 调用可 replay，工作流可 checkpoint。
5. **规则先行、LLM 兜底**：护栏先用廉价规则，LLM judge 只在必要处（成本排序）。
6. **失败不阻断**：评审 fail-open、记忆合并失败保持原样、HITL 缓存降级。

---

## 五、面试话术

> "按 `Agent = Model + Harness` 的说法，我项目里**模型之外、我自建的工程都是 harness**。
> 它分四层：**执行引擎**（通用 ReAct loop）、**控制**（ToolGovernor 权限/限流/超时/HITL）、
> **观测**（trace + artifact + replay）、**评测**（golden + 回归门禁）。
> 核心原则是**用代码管边界、用模型管语义**，还留了 `harness_enabled` 可整体回退。
> 对标 Claude Code / Codex 后，我补了两个细节：**审批缓存**和**参数级类型化策略谓词**。"

**记忆锚点**：模型是野马，Harness 是缰绳 + 鞍 + 行车记录仪 + 年检。

---

## 六、边界：项目 ≠ Harness（别说错）

```
项目（= 一个应用 / 产品）
├── 业务 / 产品层   要做什么：视频问答、推荐、前端页面   ← 应用逻辑，不算 Harness
└── Agent
     ├── Model
     └── Harness    怎么让模型可靠地做                  ← 驾驭设施
```

- **准确**："我项目是一个 **Agent 应用**；其中模型之外、我自建的工程是一整套 **harness**。"
- **不准确**："我项目**就是**一个 harness 项目"——业务逻辑与前端不是 harness，容易被追问垮。

判据：**和"驾驭模型"有关 → Harness；和"产品要回答什么"有关 → 业务。**

---

## 七、常见概念误区：RAG 与 Harness 不是对立的

- **"RAG 过时了"是半真半假**：没死的是检索，死的是"**裸 RAG**"（一次性 检索→拼 prompt→生成）。
  它演化成了 **Agentic RAG**：由 agent 决定**要不要检索、检索几次、怎么改写、要不要重排**。
- **"Harness 很虚"有合理处**：harness 是老词被重新包装；但它命名了一个真实现象——
  `prompt engineering → context engineering → harness engineering`，
  **模型之外的工程决定了产品能不能用**。
- **关键**：**RAG ⊂ Harness**。RAG 是一种能力（工具/通道），Harness 是整套设施；
  二者不是竞争对手。"RAG vs Harness" 是类别错误。

```
Harness
├── Agent Loop
├── 能力 / 工具
│    └── RAG 检索   ← RAG 在这里
├── 控制 / 观测 / 评测
```

**面试答法**："RAG 没死，是被 agentic 检索吸收了；RAG 是 harness 里的一个工具，不是 harness 的对立面。"
