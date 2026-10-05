# VAgent 业务评测指标

**门禁只看 [`ci_metrics.md`](ci_metrics.md)。** 本页表格里带 **live** 或未进 `.github/workflows/ci.yml` 的数字（含路由 80.7%、ReAct 工具 95.7%）是本机实测，run-to-run 会漂，**不是 CI 门禁**。

- 生成时间（UTC）：2026-09-02（本机 `golden_set.py --no-llm` 等脚本实测）
- 场景：ViewHub 视频助手（问答 / 推荐 / 个人数据 / 闲聊）

## 规模摘要（live / 本机，非正式门禁）

| 项 | 规模 / 结果 |
|----|-------------|
| 路由评测集 `fixtures/routing_golden.jsonl` | **357** |
| 融合路由整体准确率 | **80.7%**（288/357） |
| 易例 | **84%**（235/281） |
| 歧义 | 64%（28/44） |
| 跑题 | 78%（25/32） |
| 双路共识子集 | **99.0%**（100/101） |
| 行为门禁 `behavior_golden_set.py` | **22/22** |
| SSE 离线回归 | **23/23** |
| 视频内回答护栏 `synonym_video_qa_eval.py` | **22/22**（命中 14/14，硬负例拒答 8/8） |
| ReAct 评测集 `fixtures/react_eval_cases.jsonl` | **161**（视频内回答 78 / 平台问答 47 / 闲聊 36） |
| ReAct 工具选择准确率（live） | **95.7%**（132/138） |
| ReAct 平均步数（live） | **1.73** |
| 语义重试评测集 `fixtures/semantic_retry_cases.jsonl` | **30**（20 常规 + 10 首轮难命中） |
| 语义重试 ablation（证据充足率，live） | **63.3%→93.3%** |
| stop_on_sufficient ablation（video_qa 平均步数，live） | **2.00→1.00** |
| 记忆取代阈值校准（相似度，dup / para 命中） | **50/50 / 1/50** |
| 记忆冲突判定准确率（LLM Judge，live） | **99.3%**（dup 100% / para 98% / distinct 100%） |
| 检索召回评测集 `fixtures/retrieval_eval_cases.jsonl` | **45**（3 视频 / 24 片段） |
| 检索召回（词面基线） | recall@5 **82.2%** / MRR **69.1%** |
| 意图分类微调（基座 / few-shot / **LoRA**） | **54.0% / 69.4% / 89.1%** |
| pytest collect | **741** |

> 说明：大盘含歧义/跑题，整体低于「仅易例」属预期；共识子集高，说明双路一致时更稳。不要写成「融合相对关键词大幅提升」（当前离线环境下二者接近）。

## ReAct Agent 评测（工具选择 / 步数）

- 评测脚本：`scripts/eval_react_metrics.py`（真实 Router + 真实 ReAct 循环，检索后端 mock，摆脱 DB 依赖）
- 评测集：`fixtures/react_eval_cases.jsonl`（**161** 例：视频内回答 78 / 平台问答 47 / 闲聊跑题 36）
- 测量口径：工具选择准确率在「路由正确 + 属于 ReAct workflow」的样本上统计（分母 138）
- 实测（2026-09-17，live 真实 LLM `deepseek-chat`，连跑两次取第二次）：

| 指标 | 结果 |
|------|------|
| 路由准确率 | **85.7%**（138/161） |
| 工具选择准确率 | **95.7%**（132/138） |
| 平均步数 | **1.73** |
| 步数分布 | 1 步 ×41、2 步 ×112 |
| 停止原因分布 | `answered` ×153 |
| 异常 | 0 |

> run-to-run 波动约 ±1%（LLM 随机性）：另一次为路由 85.1%、工具 94.9%。

**评测发现（已修）**

- **Chat ReAct 工具从未真正执行**：`chat_with_tools` 返回规范化结构 `tool_name`，而 `chat_react.py` 只读 OpenAI 原生 `tc["function"]["name"]`，导致工具名恒为空串、`_exec_tool("")` 永远返回空。修复前工具选择准确率 **76.9%**（模型“调了工具”但没生效），修复后 **84.6%**（29 例）。已加回归测试 `test_chat_react_executes_normalized_tool_call`。
- **`retrieve_knowledge` 与 `retrieve_platform_docs` 职责重叠**：模型在两者之间摇摆。已合并为单一 `retrieve_knowledge` 工具，内部同时检索视频元数据（`video_info`）与平台 FAQ，去重后按分排序。合并后工具选择准确率升至 **95.7%**（161 例）。

**badcase（161 例，第二次运行）**

- 路由（23 条）：主要是 `video_qa → chat`，如「这个视频的简介是什么」「视频主题是什么」「片尾征稿说了啥」——**关键词未覆盖、语义路由在本环境降级**（日志「embedding 无区分度」），属环境导致的漏判；其次 `chat → recommend`，如「推荐一个餐厅给我」「火锅店推荐」被「推荐」误触发。
- 工具（6 条）：
  - 该调未调：「这个助手能做什么」「你会做什么」「帮助」「我该从哪开始」——模型直接作答，对「帮助/你会做什么」尚可接受，但漏检。
  - 不该调却调：「比特币行情」「星座运势」——跑题问题仍触发检索，浪费一次调用。

> 口径说明：步数 = ReAct 循环迭代次数（1 步=直接作答，2 步=检索一次后作答）。live 模式需要有效 `DEEPSEEK_API_KEY`；离线 replay 模式（默认）用于 CI 自检，不计入模型能力。本环境语义路由降级为纯关键词，路由准确率不具跨环境可比性，仅作趋势参考。


## 检索召回质量（recall@k / MRR / hit@k）

补齐此前的空缺：项目一直只评「路由 / 工具 / 步数」，**没评「检索准不准」**。

- 脚本：`scripts/eval_retrieval_metrics.py`；用例：`fixtures/retrieval_eval_cases.jsonl`
  （24 片段语料 + **45** 条标注 query，3 个视频）
- 双后端：
  - `offline`（默认，零依赖）：对语料做**词面相似度**排序（trigram Jaccard），给出**下限基线**
  - `dual`：调生产检索器 `dual_recall_and_rerank`（pgvector + 关键词 + rerank），需 DB + DB 语料
- 实测（2026-09-17，offline 词面基线）：

| 指标 | recall@1 | recall@3 | recall@5 | MRR | hit@5 |
|------|---------|---------|---------|-----|-------|
| 词面基线 | 60.0% | 77.8% | **82.2%** | **69.1%** | 82.2% |

> 结论：
> 1. **词面基线 recall@5 = 82.2%**，未召回的 8 条集中在话题词不重合的短问句（如「异常怎么处理」）。
> 2. 这是**下限**：生产检索器走 **embedding 语义召回 + LLM/规则 rerank**，应显著高于词面基线；
>    但本环境 embedding 降级（「无区分度」），故先用词面基线占位，`--dual` 已写好待 DB 复核。
> 3. 诚实边界：语料与标注为合成；绝对数字需连 DB 用真实语料重建 fixture 后复核。


## Agent Loop 执行引擎（app/harness/agent_loop.py）

- 两个 ReAct agent（chat / video_qa）的"决策→执行→观察→终止"统一抽到 `app/harness/agent_loop.py`，
  对标 deepseek-harness `ReactLoopAgent`、kimi-cli `kosong.step()`。
- 关键改进：
  - **typed stop_reason**：`answered | max_steps | duplicate_repeat | timeout | error | sufficient`，
    落到 `react_stop_reason` 并进入 eval 统计（本数据集 153 条全部 `answered`）。
  - **重复调用先 nudge 再停**：连续重复第 1 次注入"换关键词/角度"提醒，第 2 次才强制终止
    （config `agent_loop_nudge_after` / `agent_loop_force_stop_after`）。
  - **统一 observation 格式**：空结果 →「（工具无返回内容）」，异常 → `<system>ERROR: ...</system>`。
  - **循环级 wall-clock 预算**：`agent_loop_deadline_seconds`（默认 45s），超时 `stop_reason=timeout`。
- 重构后台（live）：路由 **85.7%** / 工具 **95.7%** / 平均 **1.73 步**——**与重构前一致，行为保持不变**。

> **诚实发现：nudge 在真实场景几乎不触发。**
> 161 例 live 评测 `duplicate_repeat` 出现 **0 次**；另做真机冒烟（强制工具返回空、诱导重试），
> 模型每步都**主动换关键词**（`量子纠缠 最新研究进展` → `量子纠缠 研究` → `量子纠缠`），
> 从未用完全相同参数重复调用。说明**能力强的模型天然会探索**，nudge 属于**防呆保险**
> （防弱模型/异常情况下卡死），机制正确性由单测覆盖，不是主要收益点。

### stop_on_sufficient ablation（省一次 LLM 调用）

- 脚本：`scripts/eval_stop_on_sufficient.py`；用例：`react_eval_cases.jsonl` 的 **78** 条 video_qa
- 对比：证据充足时，**让模型自己决定**（OFF，默认）vs **引擎立即收口**（ON）
- 实测（2026-09-17，live）：

| 指标 | OFF | ON |
|------|-----|----|
| 平均步数（≈LLM 调用） | **2.00** | **1.00** |
| 总步数（78 例） | 156 | 78 |
| 停止原因 | `answered` ×78 | `sufficient` ×78 |

> 结论：证据首步即充足时，提前收口把 video QA 的 ReAct **从 2 步降到 1 步，省一次 LLM 调用**。
> 口径：mock 首步即返回充足，故 1.00 是**上限**；真实收益 ≈ `P(首步充足) × 1`。
> **默认开启**（`video_qa_react_stop_on_sufficient=True`）：触发条件是 `has_sufficient_evidence`
> 为真（证据分 ≥ 阈值），不是无条件截断，所以省步不以牺牲证据充分性为代价。
> 口径提醒：本实验用固定证据 mock，**绝对质量需连 DB 用真实检索复核**；若某类视频质量下降，
> 可一键关回 False。


## 语义级重试 ablation（Semantic Retry）

- 脚本：`scripts/eval_semantic_retry.py`；用例集：`fixtures/semantic_retry_cases.jsonl`（**30** 例：
  20 例常规问法 + 10 例模糊问法/字幕专有术语）
- 方法：离线无 DB，采用**受控模拟检索**（查询命中视频「内容词」即视为召回充足，模拟"内容术语只在字幕里"）；
  对比 **关闭 / 开启** 语义重试，改写走真实 LLM（`deepseek-chat`）
- 实测（2026-09-17，live，连跑两次）：

| 指标 | 关闭重试 | 开启重试 |
|------|---------|---------|
| 证据充足率 | **63.3% / 66.7%** | **93.3% / 96.7%** |
| 首轮失败被救回 | — | **81.8% / 90.0%** |
| 平均检索次数 | 1.93 / 2.03 | 2.23 / 2.33 |

**关键发现：收益完全取决于改写质量（一次真实的提示词迭代）**

1. **第一版改写提示词过于泛化**（只说"换个角度、换同义词"），模型倾向输出「内容/主题/介绍」这类泛词，
   30 例 × 3 轮实测**救回率 0.0%**——功能等于没生效。
2. **定位后修改提示词**：明确要求"用该主题下的**具体领域术语/专业名词**，不要用泛词，
   列举最可能出现的 3–5 个概念"（不含任何测试用例示例，避免作弊）。
3. 重测：救回率升到 **81.8–90.0%**，证据充足率 **63.3%→93.3%**。

> 结论：语义重试本身只是"换角度"的机制，**效果几乎完全由改写提示词决定**——泛化改写 ≈ 0 增益，
> 领域术语改写 ≈ 80–90% 救回。代价约 **+0.3 次**检索（默认最多 1 轮），成本可接受。
> 口径提醒：受控模拟用"内容词命中"近似检索，对 OFF/ON 是同一把尺子，相对增益可比；
> 提示词是在该用例集上迭代的，**存在对测试集调参成分**，真实收益需线上验证。


## 长期记忆「相似取代」阈值校准

- 脚本：`scripts/eval_memory_supersede.py`；用例：`fixtures/memory_supersede_cases.jsonl`（**150** 例，dup/para/distinct 各 50）
- 背景：`save_memory` 用 `similarity() >= memory_supersede_threshold` 判断新旧记忆是否同一偏好。
  阈值原为拍脑袋的 0.6，本实验做校准。
- 方法：相似度优先走 DB 的 pg_trgm `similarity()`；DB 不可用时用 **Python 复刻同公式**
  （trigram 集合 Jaccard），离线也能出数。句对分三类：`dup`（同文重复）/ `para`（同义改写）/ `distinct`（不同偏好）。
- 实测（2026-09-17，Python 复刻，与线上同算法）：

| 阈值 | dup 命中 | para 命中 | distinct 误伤 |
|------|---------|----------|--------------|
| 0.40 | 50/50 | 5/50 | 19/50 |
| **0.50（校准后默认）** | **50/50** | 1/50 | **0/50** |
| 0.60（原默认） | 34/50 | 0/50 | 0/50 |
| 0.80 | 34/50 | 0/50 | 0/50 |

> 结论：
> 1. **阈值从 0.6 下调到 0.5**：零误伤不变，dup 命中从 34/50 升到 **50/50**。
> 2. **词面信号抓不到同义改写**（`para` 命中 0–1/50）——"喜欢科幻" → "偏爱科幻片" 这类
>    **语义级偏好变更**不会被相似度取代。
> 3. 能力边界清晰：相似度解决"重复提取去重"，**不解决"语义冲突"** → 下一节升级。


## 记忆冲突判定：相似度 → LLM Judge（一次由数据驱动的升级）

上文校准暴露了相似度的上限。进一步测试 **embedding** 也不行（distinct 误伤 6–11/20）——因为
「喜欢咖啡 / 喜欢茶」「喝咖啡 / 不喝咖啡」**结构相同、语义相反**，任何相似度都不可分，
只有 LLM 能判。

于是升级为 ragent 同款 **LLM Judge**（`app/agents/memory_judge.py`）：写入前让 LLM 对比
已有记忆与新记忆，输出 `ADD / SUPERSEDE / NOOP`。

- 脚本：`scripts/eval_memory_judge.py`；用例：同 `fixtures/memory_supersede_cases.jsonl`（**150** 例）
- 判定：dup/para 期望「不新增」（SUPERSEDE 或 NOOP），distinct 期望 ADD
- 实测（2026-09-17，live，`deepseek-chat`）：

| 类别 | 相似度（0.5） | **LLM Judge** | Judge 动作分布 |
|------|--------------|--------------|---------------|
| dup（重复提取） | 50/50 | **50/50（100%）** | NOOP 34 + SUPERSEDE 16 |
| para（同义改写） | **1/50** | **49/50（98%）** | SUPERSEDE 49 + ADD 1 |
| distinct（不同偏好） | 50/50 | **50/50（100%）** | ADD 50 |
| **整体** | — | **99.3%** | — |

> 结论：
> 1. **LLM Judge 把同义改写命中率从 1/50 提到 49/50**——这是相似度做不到的。
> 2. 唯一"错例"`喜欢钢琴 / 会弹钢琴` → ADD 也说得通（喜欢≠会弹），实际接近满分。
> 3. 机制定位：**相似度做零成本兜底，LLM Judge 做主判定**（`memory_judge_enabled=False` 可退化为纯相似度）。
> 4. 成本：每次写入多一次低 token 的 LLM 调用；提取侧用**攒批**（`memory_extract_min_turns=3`）
>    把提取调用降到「每 3 轮 1 次」，抵消 Judge 的额外开销。


## 复现

```bash
cd ai-end
python3 scripts/golden_set.py --no-llm
python3 scripts/behavior_golden_set.py
python3 scripts/sse_regression.py --offline
python3 scripts/synonym_video_qa_eval.py
python3 scripts/eval_react_metrics.py            # ReAct 离线自检（零 token）
python3 scripts/eval_react_metrics.py --live     # ReAct 真实 LLM（需有效 DEEPSEEK_API_KEY）
python3 scripts/eval_semantic_retry.py --offline # 语义重试 ablation 离线自检
python3 scripts/eval_semantic_retry.py           # 语义重试 ablation（真实 LLM 改写）
python3 scripts/eval_stop_on_sufficient.py --offline # 省步 ablation 离线自检
python3 scripts/eval_stop_on_sufficient.py       # 省步 ablation（真实 LLM）
python3 scripts/eval_memory_supersede.py --python # 记忆取代阈值校准（离线，零依赖）
python3 scripts/eval_memory_supersede.py          # 记忆取代阈值校准（优先用 DB pg_trgm）
python3 scripts/eval_memory_judge.py --offline    # 记忆冲突判定 LLM Judge 离线自检
python3 scripts/eval_memory_judge.py              # 记忆冲突判定 LLM Judge（真实 LLM）
python3 scripts/eval_retrieval_metrics.py         # 检索召回质量（离线词面基线）
python3 scripts/eval_retrieval_metrics.py --dual  # 检索召回质量（生产检索器，需 DB）
python3 -m pytest tests --collect-only -q --no-cov
# 可选一键重写本文件：
python3 scripts/run_metrics_report.py
```
## 模型微调（意图分类 · LoRA）

用 **LoRA 微调 Qwen3-0.6B** 做意图分类（4 类）。

- **数据**：人工标注 `fixtures/routing_golden.jsonl`（**357**）作验证集核心；
  LLM 合成 `fixtures/routing_augmented.jsonl`（**800，仅进训练集**）。
  划分：**验证集 248 例全部人工标注**（held-out），训练集 **909**（人工 109 + 合成 800）。
- **训练**：LoRA `r=8/alpha=16/dropout=0.05`，目标 `[q,k,v,o]_proj`，**只在 assistant 段算 loss**；
  Tesla V100-32G，200 步，**~3 分钟**（train_loss 0.016）。
- **公平 baseline**：基座不仅测 zero-shot，还测 **few-shot(8)**（不让基座输在提示词上）。

| 指标 | 基座(zero) | 基座+few-shot(8) | **LoRA** |
|------|-----------|------------------|---------|
| **整体** | 54.0%（134/248） | 69.4%（172/248） | **89.1%（221/248）** |
| easy | 47.7% | 70.9% | **91.3%** |
| ambiguous | 52.3% | 52.3% | **90.9%** |
| offtopic | 90.6% | 84.4% | 75.0% |

> 结论（诚实口径）：
> 1. few-shot 把基座从 54% 提到 **69.4%**（提示词工程有效）；**LoRA 再提到 89.1%**，净增益 **+19.7 点**。
> 2. LoRA 在 **ambiguous 难例** 上优势最大（52% → 90.9%）；但 **offtopic 反而下降**（90.6% → 75%）
>    ——训练集跟主题相关性强的样本多、跑题样本少，属**数据分布问题**，是下一步改进点。
> 3. 口径：验证集 248 例**全部人工标注**、held-out；合成数据只进训练集，不污染验证。
> 4. **行为类任务（分类/格式）适合微调；知识问答仍用 RAG。**
