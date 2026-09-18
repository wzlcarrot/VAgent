# 模型微调（意图分类 · LoRA）

> 用 **LoRA 微调 Qwen 0.6B** 做**意图分类**，与项目现有关键词路由（**80.7%**）对比。

## 一、为什么选这个任务

| 考虑 | 说明 |
|------|------|
| **有真数据** | `fixtures/routing_golden.jsonl`：**357 例、4 类意图、含难度分层** |
| **有 baseline** | 关键词路由 80.7%、ReAct 子集 85.7%——**可直接对比** |
| **会考微调** | 岗位要求微调经验；这是**真任务 + 真指标**，不是"跑通 demo" |
| **可量化** | 准确率 + 按难度（easy/ambiguous/offtopic）分层 |

**任务**：`问题 → {video_qa / recommend / user_data / chat}` 四分类。

## 二、脚本

```
scripts/finetune/
  common.py        标签集、系统提示、数据格式
  augment_data.py  LLM 合成训练数据（仅训练集，扩到 800）
  export_sft.py    人工报注 → 验证集(250)；人工剩余 + 合成 → 训练集(909)
  train_lora.py    LoRA 微调（只在 assistant 段算 loss）
  eval_intent.py   基座(zero) vs 基座(few-shot) vs LoRA，按难度分层
  predict.py       单条预测（本地看效果）
```

## 三、服务器操作（AutoDL）

**① 无卡模式：装环境 + 下模型**
```bash
pip install -U transformers peft datasets accelerate
export HF_ENDPOINT=https://hf-mirror.com
pip install modelscope
python -c "from modelscope import snapshot_download; snapshot_download('Qwen/Qwen2.5-0.6B-Instruct')"
# 记下模型路径（一般 ~/.cache/modelscope/hub/Qwen/Qwen2.5-0.6B-Instruct）
```

**② 传项目（只传 finetune 相关）**
```bash
# 本地：把 data/finetune 和 scripts/finetune 打包上传到 autodl-tmp
```

**③ 切有卡模式：造数据 + 训练**
```bash
# 合成训练数据（可选，仅训练集；需 LLM key）
python3 scripts/finetune/augment_data.py --per-intent 200
# 划分：验证集 250 人工 / 训练集 = 人工剩余 + 合成
python3 scripts/finetune/export_sft.py --val-size 250
# 训练
python3 scripts/finetune/train_lora.py \
  --base-model /root/autodl-tmp/models/Qwen--Qwen3-0.6B/snapshots/master \
  --output /root/autodl-tmp/lora-intent \
  --epochs 3 --max-steps 200
```

**④ 评测**
```bash
python3 scripts/finetune/eval_intent.py \
  --base-model ~/.cache/modelscope/hub/Qwen/Qwen2.5-0.6B-Instruct \
  --adapter /root/autodl-tmp/lora-intent \
  --compare-router
```

## 四、关键设计点（面试可讲）

1. **只在 assistant 段算 loss**：prompt 段 label 置 `-100`，不学"复述问题"（`build_example`）。
2. **分层验证集**：难例（ambiguous/offtopic）优先进验证集，专门看**难例提升**。
3. **对比三方**：基座 vs LoRA vs 关键词路由——**不只报一个数**。
4. **LoRA 参数**：`r=8, alpha=16, dropout=0.05, target=[q,k,v,o]_proj`。

## 五、实测结果（公平口径，248 例人工验证集）

| 指标 | 基座(zero) | 基座+few-shot(8) | **LoRA** |
|------|-----------|------------------|---------|
| **整体** | 54.0% | 69.4% | **89.1%** |
| easy | 47.7% | 70.9% | 91.3% |
| ambiguous | 52.3% | 52.3% | **90.9%** |
| offtopic | 90.6% | 84.4% | 75.0% |

> - **fair baseline**：基座也测了 few-shot（69.4%），**不让基座输在提示词上**；LoRA 净增 **19.7 点**。
> - **数据**：验证集 248 例**全人工标注**；合成 800 条**只进训练集**，不污染验证。
> - **诚实发现**：LoRA 在 offtopic 上**下降**（训练集跑题样本少）——数据分布问题，下一步补。
> - 训练 V100 ~3 分钟，train_loss 0.016（**看验证集，不看 loss**）。

## 六、面试话术

> "岗位需要微调经验，我用项目现成的 **357 例意图标注**做了 **LoRA 微调 Qwen0.6B** 的意图分类：
> 数据分层划分（难例进验证集）、**只在 assistant 段算 loss**、LoRA 只训 0.6% 参数；
> 评测**三方对比**——基座 / LoRA / 关键词路由（80.7%），按难度分层看难例提升。
> **关键不是'会训'，是'用什么数据、怎么评、和谁比'。**"

## 七、与 RAG 的关系（追问必答）

> "意图分类适合微调（**行为固定、类别明确**）；但**知识问答我不会微调**——那是 RAG 的活（知识会变、要溯源）。
> **行为 → 微调；知识 → RAG。** 我项目两条路都用：回答靠 RAG，路由靠微调。"

## 八、接入项目路由（怎么用）

微调模型已接入 `Router`：开启配置后，**路由优先用微调模型**，不可用/失败自动回退现有混合路由。

**配置（`app/config.py` 或环境变量）**：
```bash
FINETUNE_INTENT_ENABLED=true
# 合并后的完整模型目录（基座+LoRA）
FINETUNE_INTENT_MODEL_PATH=/home/tourist/agent/vagent-intent-qwen3-0.6b
```

**运行**：无需改代码，`Router` 自动使用：
```
问题 → 微调模型分类 → video_qa/recommend/user_data/chat（method=finetune）
     → 模型不可用 → 回退关键词/语义/LLM 混合路由
```

**代码位置**：`app/tools/finetune_intent.py`（懒加载 + 失败静默回退）+
`app/agents/router.py::_hybrid_route_full_impl`（微调通道优先）。

**实测**（本地，合并模型）：
```
这个视频讲了什么  → video_qa_workflow  (finetune)
主题讲的是什么    → video_qa_workflow  (finetune)   ← 关键词路由会错
推荐点科幻视频    → recommend_workflow (finetune)   ← 关键词路由会错
我收藏了哪些视频  → user_data_workflow (finetune)
怎么上传视频      → chat_workflow      (finetune)
```

> ⚠️ 生产建议：把分类模型**单独部署为服务**（HTTP/gRPC），路由调用它——
> 内置加载 1.2G 模型会占内存、CPU 单条推理 ~1s，不适合高并发。本项目内置是为演示"项目能用微调模型"。
