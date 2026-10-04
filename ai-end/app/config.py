"""
全局配置 —— 全部用环境变量覆盖，避免代码里散落 magic numbers
"""
import os
from typing import Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

try:
    from dotenv import load_dotenv
    _env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(_env_path):
        load_dotenv(_env_path)
    elif os.path.exists(".env"):
        load_dotenv(".env")
except ImportError:
    pass


class Settings(BaseSettings):
    app_name: str = "ViewHub AI Agent"
    debug: bool = False

    # ─── 数据库 ───
    pg_host: str = "127.0.0.1"
    pg_port: int = 5432
    pg_user: str = "postgres"
    pg_password: str = ""
    pg_database: str = "viewhub"
    db_pool_size: int = 20

    # ─── LLM ───
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    # DeepSeek 多模态（Vision）：deepseek-flash 支持图文混合输入
    deepseek_vl_api_key: str = ""  # 留空回退 deepseek_api_key
    deepseek_vl_base_url: str = "https://api.deepseek.com"
    deepseek_vl_model: str = "deepseek-flash"
    llm_provider: str = "deepseek"
    # 路由器意图分类专用 provider；留空则跟随 llm_provider（见 LLM_tools.chat_with_tools_router）
    router_llm_provider: str = ""
    # 路由分歧时用显式 CoT（先逐步推理再裁决意图）替代直接 tool-call 判定
    router_cot_enabled: bool = True
    # ─── 微调意图分类模型（LoRA Qwen3-0.6B）接入路由 ───
    # 开启后优先用微调模型判意图，不可用/失败则回退现有混合路由
    finetune_intent_enabled: bool = False
    # 合并后的完整模型目录（基座+LoRA）或 adapter 目录
    finetune_intent_model_path: str = ""
    # 微调模型分类的置信度（用于 RouteDecision）
    finetune_intent_confidence: float = 0.95
    # 生成上限（标签很短，16 足够）
    finetune_intent_max_new_tokens: int = 16

    # ─── LLM Retry ───
    llm_retry_max_attempts: int = 3
    llm_retry_base_delay: float = 1.0
    llm_retry_max_delay: float = 8.0

    # ─── Redis ───
    redis_host: str = "127.0.0.1"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str = ""
    redis_cooldown_seconds: float = 5.0

    # ─── Video service ───
    video_service_url: str = "http://127.0.0.1:7071"
    # 给前端浏览器访问的 cover URL 前缀（应公网可访问）。
    # 默认等于 video_service_url；生产部署到独立域名时通过环境变量覆盖。
    public_video_url: str = "http://localhost:4091/default-cover.svg"  # 前端占位封面（无外部视频服务时）
    # 视频封面文件根目录（挂载进容器，sourceName 为 cover/xxx 相对路径）
    cover_dir: str = "/app/data/file/cover"

    # ─── CORS ───
    cors_origins: str = "http://localhost:4000,http://127.0.0.1:4000,http://localhost:4091,http://127.0.0.1:4091"

    # ─── Context 三层隔离 ───
    context_max_rounds: int = 5
    context_summary_ttl: int = 3600
    context_ttl: int = 7200
    compact_token_threshold: int = 3000
    compact_cooldown_seconds: int = 300

    # ─── 长期记忆治理（借鉴 ragent：冲突取代 + 容量上限 + 注入护栏）───
    # 新记忆与已有有效记忆相似度 >= 阈值时，旧记忆置 invalid_at（软失效）。
    # 0.5 来自 150 例校准（零误伤且 dup 命中 50/50）；0.6 只能命中 34/50。
    memory_supersede_threshold: float = 0.5
    # 单用户活跃记忆上限，超出按「有效分」从低到高软淘汰
    memory_max_per_user: int = 50
    # 注入提示词的记忆块字符上限（防止记忆挤占上下文）
    memory_inject_max_chars: int = 800
    # 词面召回为空时，兜底按「有效分（时间衰减+频次）」取最近记忆，避免静默丢弃
    memory_recall_fallback: bool = True
    # 记忆召回模式：hybrid=关键词∪余弦（默认）；lexical=仅关键词；semantic=仅余弦
    memory_recall_mode: str = "hybrid"
    # 记忆语义召回（余弦）：关键词 ∪ 余弦双通道
    memory_semantic_recall_enabled: bool = True
    memory_semantic_threshold: float = 0.45
    # 融合方式：
    #   additive（默认、直观）      final = w_base×时效频次 + w_sem×余弦
    #   multiplicative（时效主导）  final = 时效频次 × (1 + weight×余弦)
    memory_fusion_mode: str = "additive"
    memory_fusion_w_base: float = 0.6
    memory_fusion_w_sem: float = 0.4
    # multiplicative 模式的加成权重
    memory_semantic_weight: float = 0.5
    # 记忆合并（二次压缩）：活跃数超过 trigger 时，把最低分的 batch 条交给 LLM 合并成更少条目
    memory_consolidate_enabled: bool = True
    memory_consolidate_trigger: int = 40
    memory_consolidate_batch: int = 10
    # 每轮最多合并几次（合并有「地板」，合不动就停；仍超上限由容量淘汰兜底）
    memory_consolidate_max_rounds: int = 3
    # 写入前用 LLM Judge 判冲突（ADD/SUPERSEDE/NOOP）；关闭则退化为相似度启发式
    memory_judge_enabled: bool = True
    # 攒够 N 轮对话才跑一次记忆提取（借鉴 ragent 的 pending 阈值；1=逐轮提取）
    memory_extract_min_turns: int = 3
    # 软失效记忆的保留天数，超过后归档并从主表清理（0 表示不自动归档）
    memory_archive_after_days: int = 30
    # 归档后台任务运行间隔（秒），默认每天一次
    memory_archive_interval_seconds: int = 86400

    # ─── Auth ───
    token_ttl_seconds: int = 7 * 24 * 3600
    # 登录 cookie 是否要求 HTTPS（生产环境设 True；本地 http 开发保持 False）
    cookie_secure: bool = False

    # ─── 测试账户（从环境变量读取，避免硬编码） ───
    test_account_enabled: bool = False
    test_account_email: str = ""
    test_account_password_md5: str = ""
    test_account_user_id: str = ""
    test_account_nickname: str = ""
    test_account_avatar: str = ""

    # ─── Embedding ───
    embed_model_name: str = "BAAI/bge-base-zh-v1.5"
    embed_cache_max: int = 5000
    embed_cache_ttl: int = 86400

    # ─── Harness ───
    harness_enabled: bool = True
    # 工具结果被截断时，把完整输出落盘并追加续读提示
    tool_result_spill_enabled: bool = True
    # 工具结果截断保留哪头：head=前 N（文件/列表，默认）；tail=后 N（命令输出，报错在末尾）
    tool_result_truncate_keep: str = "head"
    # Hook 引擎开关（before/after 工具调用与消息事件）
    hooks_enabled: bool = True
    # Run Trace JSONL（observe first, interpret later）
    trace_enabled: bool = True
    trace_root: str = "data/traces"
    # SSE 是否推送 harness 调试事件（node/tool/checkpoint）
    harness_sse_enabled: bool = True
    # 视频问答：是否用 LLM 增强 query 改写（失败回退规则）
    video_qa_llm_rewrite: bool = True
    # 视频问答：生成后 corrective（证据校验 + 最多一次补搜）
    video_qa_corrective: bool = True
    # 视频问答：L2 grounding 用短 LLM judge（演示模式走 replay，不关闭逻辑）
    video_qa_llm_grounding: bool = True
    # 视频问答：Bounded ReAct 检索（最多 N 次 search_video_chunks）
    video_qa_react_enabled: bool = True
    video_qa_react_max_steps: int = 3
    # 视频问答：独立评审 Agent（Reflection，与生成上下文隔离，只做质量复核）
    video_qa_critic_enabled: bool = True
    # 视频问答：证据不足时语义重试（换角度改写后重检索，最多 N 次）
    video_qa_semantic_retry_enabled: bool = True
    video_qa_semantic_retry_max: int = 1
    # LLM Replay（CI / snapshot 测试）
    llm_replay_enabled: bool = False
    llm_replay_fixtures_dir: str = "fixtures/llm_replay"
    # 演示模式：启用 LLM replay（mock LLM 调用），检索/改写/grounding 逻辑与生产一致
    demo_mode: bool = False
    # orchestration_mode: workflow=LangGraph；agent=Bounded ReAct 主引擎（chat + video_qa 均可用 ReAct）
    orchestration_mode: str = "workflow"
    chat_react_max_steps: int = 3
    # ─── 通用 Agent Loop 引擎（app/harness/agent_loop.py）───
    # 连续重复工具调用达到该次数开始 nudge（注入提醒让模型换角度）
    agent_loop_nudge_after: int = 1
    # 连续重复达到该次数强制终止（借鉴 deepseek/kimi 的重复调用防护）
    agent_loop_force_stop_after: int = 2
    # 循环 wall-clock 预算（秒）；0=不限制。防止 max_steps × 单步超时叠加过长
    agent_loop_deadline_seconds: float = 45.0
    # video_qa：证据已充足时提前结束检索循环（78 例 ablation：平均步数 2.00→1.00，省一次 LLM 调用）
    video_qa_react_stop_on_sufficient: bool = True
    # 联网搜索通道占位（默认关闭；开启时走 web_search_stub）
    web_search_enabled: bool = False

    # ─── RAG 检索漏斗（recall → rerank 候选池 → top-k）───
    rag_default_top_k: int = 5
    rag_recall_budget: int = 10
    rag_rerank_candidate_limit: int = 15
    # 精排后端：cross_encoder（本地 bge-reranker）优先，失败自动降级 llm，再失败用召回原始分
    rag_rerank_backend: str = "cross_encoder"
    rag_rerank_model: str = "BAAI/bge-reranker-base"
    rag_rerank_cache_dir: str = ""
    # 批级 EvidenceGate：整批最高 rerank 分低于此阈值则丢弃全部证据（0=关闭）
    rag_evidence_gate_min_score: float = 0.35
    # 无分可读时是否整批丢弃（True=fail-closed，避免 demo/降级路径乱放行）
    rag_evidence_gate_fail_closed_missing_score: bool = True
    # 检索效果评测 HTTP 接口（仅返回召回，不调用生成 LLM）
    rag_eval_enabled: bool = True

    # 同步 workflow 执行的线程池并发数（每请求并行 2 路 workflow，建议 ≥ 4 的倍数）
    agent_async_max_workers: int = 8

    # ─── LLM 熔断 ───
    llm_circuit_failure_threshold: int = 5
    llm_circuit_cooldown_seconds: float = 60.0
    llm_circuit_enabled: bool = True

    # ─── weekly golden（反馈入库）───
    weekly_golden_enabled: bool = True
    weekly_golden_root: str = "data/weekly_golden"

    # ─── 流式并发许可 ───
    chat_concurrent_enabled: bool = True
    chat_concurrent_max_global: int = 100
    chat_concurrent_max_user: int = 3

    # ─── 索引 SLA ───
    # pending 数 ≥ 该阈值时 Admin / business-quality 打 pending_alert
    index_pending_alert_threshold: int = 10
    # 启动兜底补索引条数
    index_backfill_limit: int = 50

    # ─── 视频 ASR 字幕（PostgreSQL video_subtitle_segment + subtitle_* 向量块）───
    # ViewHub projectFolder，例如 /data/viewhub（其下应有 file/video/...）
    video_storage_root: str = ""
    video_asr_enabled: bool = False
    video_asr_model: str = "tiny"
    video_asr_device: str = "cpu"
    video_asr_compute_type: str = "int8"
    video_asr_language: str = "zh"
    # 索引前合并相邻 ASR 句，控制向量条数
    video_asr_merge_max_chars: int = 280
    video_asr_merge_max_gap_s: float = 1.0
    # ASR 字幕后处理纠错（LLM 校对，不改模型）
    video_asr_correct_enabled: bool = True
    video_asr_correct_batch_size: int = 40
    video_asr_correct_max_chars: int = 1500
    video_asr_correct_timeout_s: float = 180.0
    video_asr_correct_max_tokens: int = 8000
    # 纠错专用 LLM（留空用默认）；部分 provider 支持 effort 档位（low/high/max）
    video_asr_correct_model: str = ""
    video_asr_correct_effort: str = ""
    # 纠错可指定更强的 LLM 与 effort（留空则用默认 provider 模型）

    # ─── 推荐点击埋点 ───
    recommend_click_root: str = "data/recommend_clicks"

    # ─── HITL（Claude Code 式 ask 审批）───
    hitl_enabled: bool = True
    hitl_timeout_seconds: float = 60.0
    # 审批缓存：同会话内批准过一次（agent+tool）后不再重复问（0=关闭）
    hitl_approval_cache_ttl: int = 3600
    # 测试短路：approve | deny | 空（真实等待）
    hitl_auto_decision: str = ""

    # ─── Admin ───
    # 运营看板的访问控制：简单 API Key（生产建议改 OIDC/JWT）
    # 必须通过环境变量 ADMIN_API_KEY 配置，未配置时 /admin/* 拒绝访问（fail-closed）
    admin_api_key: str = ""

    # ─── Input limits ───
    max_question_length: int = 2000
    max_image_urls: int = 4

    @field_validator("pg_port")
    @classmethod
    def validate_pg_port(cls, v: int) -> int:
        if not 1 <= v <= 65535:
            raise ValueError(f"Invalid pg_port: {v}, must be 1-65535")
        return v

    @field_validator("redis_port")
    @classmethod
    def validate_redis_port(cls, v: int) -> int:
        if not 1 <= v <= 65535:
            raise ValueError(f"Invalid redis_port: {v}, must be 1-65535")
        return v

    @field_validator("context_max_rounds")
    @classmethod
    def validate_context_max_rounds(cls, v: int) -> int:
        if v < 1 or v > 50:
            raise ValueError(f"Invalid context_max_rounds: {v}, must be 1-50")
        return v

    @field_validator("max_question_length")
    @classmethod
    def validate_max_question_length(cls, v: int) -> int:
        if v < 10 or v > 10000:
            raise ValueError(f"Invalid max_question_length: {v}, must be 10-10000")
        return v

    @property
    def redis_url(self) -> str:
        auth = f":{self.redis_password}@" if self.redis_password else ""
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @property
    def cors_origins_list(self) -> list:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_demo_mode(self) -> bool:
        return self.demo_mode or os.environ.get("VAGENT_DEMO_MODE", "").lower() in ("1", "true", "yes")

    @property
    def effective_deepseek_vl_api_key(self) -> str:
        """多模态 provider 的 key：优先专用 key，留空回退主 DeepSeek key。"""
        return self.deepseek_vl_api_key or self.deepseek_api_key

    @property
    def effective_llm_replay_enabled(self) -> bool:
        return self.llm_replay_enabled or self.is_demo_mode

    @property
    def effective_video_qa_llm_rewrite(self) -> bool:
        return self.video_qa_llm_rewrite

    @property
    def effective_video_qa_llm_grounding(self) -> bool:
        return self.video_qa_llm_grounding

    @property
    def test_account(self) -> Optional[dict]:
        """获取测试账户配置，未启用时返回 None"""
        if not self.test_account_enabled or not self.test_account_email or not self.test_account_password_md5:
            return None
        return {
            "email": self.test_account_email,
            "password_md5": self.test_account_password_md5,
            "user_id": self.test_account_user_id,
            "nick_name": self.test_account_nickname,
            "avatar": self.test_account_avatar,
        }

    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"),
        extra="ignore"
    )


import re as _re  # noqa: E402


def is_safe_cover_source_name(name: str) -> bool:
    """封面 sourceName 安全性校验：拒绝 URL（SSRF）、路径穿越、绝对路径。"""
    if not name:
        return False
    if name.startswith(("http://", "https://")):
        return False
    if name.startswith("/") or ".." in name or "\\" in name:
        return False
    if any(c in name for c in ("\x00", "\n", "\r")):
        return False
    return True


def extract_cover_source_name(url: str) -> str:
    """从封面 URL 提取 sourceName（兼容 /ai/media/cover?sourceName= 与网关 getResource 两种格式）。"""
    m = _re.search(r"sourceName=([^&\s\"']+)", url or "")
    return m.group(1) if m else ""


def build_cover_url(cover_path: str) -> str:
    """封面 URL 规范化：
    - 公开 CDN（http/https，非网关）→ 原样返回
    - 网关 getResource / 同源 /ai/media → 提取 sourceName 重写为同源代理
    - 相对路径 → 同源代理；空 / 非法（穿越/SSRF）→ ""
    """
    if not cover_path:
        return ""
    # 含 sourceName 参数的 URL（网关或同源代理）→ 提取重写
    if "sourceName=" in cover_path:
        name = extract_cover_source_name(cover_path)
        if not is_safe_cover_source_name(name):
            return ""
        return f"/ai/media/cover?sourceName={name}"
    # 公开 CDN（普通 http/https 图）→ 原样
    if cover_path.startswith(("http://", "https://")):
        return cover_path
    # 相对路径
    if not is_safe_cover_source_name(cover_path):
        return ""
    return f"/ai/media/cover?sourceName={cover_path}"


settings = Settings()


def validate_rag_config(*, strict: bool = True) -> None:
    """
    启动时校验 RAG 漏斗与 EvidenceGate 配置（借鉴 Ragent SearchChannelProperties）。

    strict=True 时预算不满足单调收窄则抛 ValueError；否则仅打 warning。
    """
    import logging

    log = logging.getLogger(__name__)
    s = settings
    if s.rag_default_top_k <= 0:
        raise ValueError(f"rag_default_top_k 必须为正数，当前：{s.rag_default_top_k}")

    recall = s.rag_recall_budget if s.rag_recall_budget > 0 else s.rag_default_top_k
    rerank_limit = (
        s.rag_rerank_candidate_limit
        if s.rag_rerank_candidate_limit > 0
        else recall
    )

    def _fail(msg: str) -> None:
        if strict:
            raise ValueError(msg)
        log.warning(msg)

    if recall < s.rag_default_top_k:
        _fail(
            f"rag_recall_budget({recall}) < rag_default_top_k({s.rag_default_top_k})，"
            "请调大 recall_budget 或调小 default_top_k"
        )
    if rerank_limit < s.rag_default_top_k:
        _fail(
            f"rag_rerank_candidate_limit({rerank_limit}) < rag_default_top_k({s.rag_default_top_k})，"
            "请调大 rerank_candidate_limit 或调小 default_top_k"
        )
    if s.rag_evidence_gate_min_score > 0 and s.is_demo_mode:
        log.info(
            "演示模式：EvidenceGate / query rewrite / grounding 与生产逻辑一致，仅 LLM 走 replay"
        )

    if s.compact_token_threshold <= 0:
        _fail(f"compact_token_threshold 必须为正数，当前：{s.compact_token_threshold}")
    if s.context_max_rounds <= 0:
        _fail(f"context_max_rounds 必须为正数，当前：{s.context_max_rounds}")
    if s.chat_concurrent_max_global < s.chat_concurrent_max_user:
        _fail(
            f"chat_concurrent_max_global({s.chat_concurrent_max_global}) "
            f"< chat_concurrent_max_user({s.chat_concurrent_max_user})"
        )
