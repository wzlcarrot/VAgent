# CI 门禁数字（可复现、不调真实 LLM）

下面这些才是流水线锁住的。`docs/metrics.md` 里 80.7% 路由、95.7% ReAct 工具选择等是**本机 live**，面试不要说成 CI 成绩。

| 项 | 门禁 | 脚本 |
|----|------|------|
| pytest + ruff | 通过；覆盖率门槛 **75%**（默认关闭的 ASR / LoRA / 启动 DDL 不计入） | `scripts/ci_run_pytest.sh` |
| vitest | 核心目录 **75%**；`src/views` 挂载门槛 **20%** | `ai-frontend` `vitest run --coverage` |
| 行为黄金集 | 22/22 | `behavior_golden_set.py` |
| 视频内回答同义护栏 | 22/22 | `synonym_video_qa_eval.py` |
| SSE 离线 | 23/23 | `sse_regression.py --offline` |
| 意图三元回归 | 脚本通过 | `intent_ternary_regression.py` |
| 关键词 easy 路由 | ≥ 80% | `tests/test_golden_set.py` |
| 检索词面 recall@5 | ≥ 70% | `eval_retrieval_metrics.py --min-recall-at-5 0.70` |

生成/核对：CI 在 golden 步骤后跑 `python scripts/ci_metrics_contract.py`。
