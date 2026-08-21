import logging
import math
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from app.agents.intent_constants import DATA_KEYWORDS, USER_DATA_MARKERS
from app.agents.workflows.constants import WorkflowType

logger = logging.getLogger(__name__)


@dataclass
class RouteDecision:
    """路由决策结果：意图 + 置信度 + 判定方式。

    confidence 是"意图置信度"（0~1），由真实信号合成：
    - keyword：关键词命中强度（route_candidates 的固定分）
    - semantic：语义示例的余弦相似度（归一化到 0~1）
    - llm：分歧时 LLM 裁决（置信度取 max(语义, 关键词, 0.7)）
    method 记录实际走的判定路径：keyword_only / consensus / llm / fallback。
    """

    workflow_type: str
    confidence: float
    method: str


def _record_router_decision(intent: str, method: str) -> None:
    """记录路由决策到 Prometheus（用于分析路由器准确率与方法分布）"""
    try:
        from app.utils.metrics import router_decisions_total
        router_decisions_total.labels(intent=intent, method=method).inc()
    except Exception:
        pass  # metrics 不可用不影响主流程


def _record_router_latency(method: str, latency_sec: float) -> None:
    """记录路由决策耗时到 Prometheus"""
    try:
        from app.utils.metrics import router_latency
        router_latency.labels(method=method).observe(latency_sec)
    except Exception:
        pass


INTENT_EXEMPLARS: Dict[str, List[str]] = {
    WorkflowType.VIDEO_QA: [
        "这个视频讲了什么内容",
        "视频的重点是什么",
        "帮我总结这个视频",
        "这个视频的作者是谁",
        "讲解一下这个视频",
        "视频里说了什么",
    ],
    WorkflowType.RECOMMEND: [
        "推荐一些好看的视频",
        "有什么推荐的",
        "推荐几个视频看看",
        "有什么好看的视频",
        "给我推荐点内容",
        "热门视频有哪些",
    ],
    WorkflowType.USER_DATA: [
        "我今天的点赞数",
        "我的收藏记录",
        "我看过哪些视频",
        "我的播放历史",
        "我点赞了哪些视频",
        "我的数据统计",
    ],
    WorkflowType.CHAT: [
        "你们平台有什么功能",
        "怎么使用这个平台",
        "帮助",
        "什么是ViewHub",
        "你们支持哪些功能",
        "平台介绍",
    ],
}


class Router:
    """
    三阶段路由：关键词（毫秒级）→ 语义相似度（10ms级）→ LLM（秒级）。

    单例模式：embedding 模型只加载一次， exemplar embeddings 全局共享。
    """

    _instance: Optional["Router"] = None
    _exemplar_embeddings: Optional[Dict[str, List[List[float]]]] = None
    _embed_lock: threading.Lock = threading.Lock()

    _embedding_cache: "OrderedDict[str, Tuple[List[float], float]]" = OrderedDict()
    _embedding_cache_lock: threading.Lock = threading.Lock()

    # 路由决策缓存：相同 (question, video_id) 在 TTL 内直接复用决策，
    # 避免重复问题重复走 embedding/LLM 裁决（LLM 慢且烧配额）。
    _route_cache: "OrderedDict[str, Tuple[float, RouteDecision]]" = OrderedDict()
    _route_cache_lock: threading.Lock = threading.Lock()

    @classmethod
    def _route_cache_max(cls) -> int:
        return 128

    @classmethod
    def _route_cache_ttl(cls) -> float:
        """路由决策缓存 TTL（秒）。太短没意义，太长会让上下文切换后的决策陈旧。"""
        return 10.0

    def clear_route_cache(self) -> None:
        """清空路由决策缓存（测试/需要强制重新路由时用）。"""
        with self._route_cache_lock:
            self._route_cache.clear()

    @classmethod
    def _cache_max(cls) -> int:
        from app.config import settings
        return settings.embed_cache_max

    @classmethod
    def _cache_ttl(cls) -> int:
        from app.config import settings
        return settings.embed_cache_ttl

    @classmethod
    def _semantic_margin(cls) -> float:
        """语义分最小区分度：top1-top2 小于该值视为无区分度，降级纯关键词。

        阈值选择：病态 embedding（如 FastEmbed 加载了假向量）时所有句子余弦相似度
        挤在 0.95-1.0，margin≈0-0.02；真实模型同一意图的近似问法 margin 通常 ≥0.03。
        取 0.03 能识别病态向量又不误伤真实近似句。
        """
        return 0.03

    def __new__(cls) -> "Router":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self.video_keywords: List[str] = ["这个视频", "讲解", "重点", "讲了什么", "说了什么",
                               "作者是谁", "up主是谁", "up主", "主播是谁", "视频简介",
                               "视频的简介", "时长"]
        self.video_exclude: List[str] = ["功能", "怎么用", "怎么使用", "如何使用", "是什么", "有什么用",
                              "怎么上传", "怎么下载", "怎么删除", "设置", "帮助", "介绍平台"]
        self.recommend_keywords: List[str] = ["推荐", "推荐点", "推荐一些", "推荐几个", "有什么好看的", "看什么", "好看的",
                                   "有什么推荐", "有啥好看的", "热门", "新出"]
        self.user_data_markers: List[str] = USER_DATA_MARKERS
        self.data_keywords: List[str] = DATA_KEYWORDS

        self._load_exemplar_embeddings()

    def _get_embedding(self, texts: List[str]) -> Optional[List[List[float]]]:
        """获取文本的 embedding 向量（LRU 缓存 + TTL）"""
        if not texts:
            return []
        now: float = time.time()
        results: List[Optional[List[float]]] = [None] * len(texts)
        miss_indices: List[int] = []
        miss_texts: List[str] = []

        with self._embedding_cache_lock:
            for i, text in enumerate(texts):
                cached = self._embedding_cache.get(text)
                if cached is not None:
                    vec, ts = cached
                    if now - ts < self._cache_ttl():
                        results[i] = vec
                        # LRU：命中后移到队尾
                        self._embedding_cache.move_to_end(text)
                        continue
                    # 过期：删掉，留给 miss 重新计算
                    self._embedding_cache.pop(text, None)
                miss_indices.append(i)
                miss_texts.append(text)

        if miss_texts:
            try:
                from app.tools.llm_tools import LLM_tools
                new_vecs: Optional[List[List[float]]] = LLM_tools.embed(miss_texts)
            except Exception as e:
                logger.warning(f"Embedding 获取失败: {e}")
                return None

            if not new_vecs or len(new_vecs) != len(miss_texts):
                return None

            with self._embedding_cache_lock:
                max_size = self._cache_max()
                for idx, text, vec in zip(miss_indices, miss_texts, new_vecs, strict=False):
                    self._embedding_cache[text] = (vec, now)
                    results[idx] = vec
                    # 满了就 pop oldest（队首）
                    while len(self._embedding_cache) > max_size:
                        self._embedding_cache.popitem(last=False)

        return results

    @staticmethod
    def _cosine_similarity(a: List[float], b: List[float]) -> float:
        """计算余弦相似度"""
        dot: float = sum(x * y for x, y in zip(a, b, strict=False))
        norm_a: float = math.sqrt(sum(x * x for x in a))
        norm_b: float = math.sqrt(sum(y * y for y in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def _max_similarity(self, query_vec: List[float], exemplar_vecs: List[List[float]]) -> float:
        """计算与示例集的最大相似度"""
        best: float = 0.0
        for ex_vec in exemplar_vecs:
            sim: float = self._cosine_similarity(query_vec, ex_vec)
            if sim > best:
                best = sim
        return best

    def _load_exemplar_embeddings(self) -> None:
        """加载意图示例的 embedding（单例，只加载一次）

        embedding 是 hash 兜底时跳过：hash 不是语义模型，示例向量全是噪音，
        加载只会浪费启动时间，语义分已在 _semantic_scores 统一降级为纯关键词。
        """
        from app.tools.embed_tools import embedding_is_fallback
        if embedding_is_fallback:
            logger.warning("embedding 为 hash 兜底，跳过意图示例加载，路由走纯关键词")
            self._exemplar_embeddings = {}
            return
        if self._exemplar_embeddings is not None:
            return
        with self._embed_lock:
            if self._exemplar_embeddings is not None:
                return
            all_exemplars: List[str] = []
            intent_boundaries: Dict[str, Tuple[int, int]] = {}
            offset: int = 0
            for intent, queries in INTENT_EXEMPLARS.items():
                all_exemplars.extend(queries)
                intent_boundaries[intent] = (offset, offset + len(queries))
                offset += len(queries)

            embeddings: Optional[List[List[float]]] = self._get_embedding(all_exemplars)
            if embeddings is not None:
                self._exemplar_embeddings = {}
                for intent, (start, end) in intent_boundaries.items():
                    self._exemplar_embeddings[intent] = embeddings[start:end]
                logger.info(f"已加载 {len(all_exemplars)} 条意图示例 embeddings")
            else:
                logger.warning("意图示例 embedding 加载失败，降级到纯关键词路由")
                self._exemplar_embeddings = {}

    def _semantic_scores(self, question: str) -> Dict[str, float]:
        """计算语义相似度得分。

        若 embedding 是 hash 兜底（非真实语义模型），返回 {} 强制走纯关键词路径，
        避免 hash 噪音制造假语义分、扭曲路由置信度。

        额外护栏：即便 embedding 标志为正常（如 FastEmbed 加载了但向量质量差），
        若语义分 top1 与 top2 区分度过小（< _SEMANTIC_MARGIN），视为无区分度，
        同样返回 {} 降级纯关键词——避免假向量把路由带偏。
        """
        from app.tools.embed_tools import embedding_is_fallback
        if embedding_is_fallback:
            return {}
        if not self._exemplar_embeddings:
            return {}
        query_vecs: Optional[List[List[float]]] = self._get_embedding([question])
        if not query_vecs:
            return {}
        query_vec: List[float] = query_vecs[0]
        result: Dict[str, float] = {}
        for intent, exemplar_vecs in self._exemplar_embeddings.items():
            result[intent] = self._max_similarity(query_vec, exemplar_vecs)
        if result:
            top_vals = sorted(result.values(), reverse=True)
            margin = top_vals[0] - top_vals[1] if len(top_vals) > 1 else 1.0
            if margin < self._semantic_margin():
                logger.warning(
                    f"语义分区分度过低 (top1-top2={margin:.3f})，判定 embedding 无区分度，"
                    f"降级纯关键词路由"
                )
                return {}
        return result

    def _is_about_current_video(self, question: str) -> bool:
        """判断问题是否关于当前视频"""
        if any(k in question for k in self.video_exclude):
            return False
        return any(k in question for k in self.video_keywords)

    def _is_personal_data_query(self, question: str) -> bool:
        """判断是否为个人数据查询"""
        has_marker: bool = any(m in question for m in self.user_data_markers)
        has_data_word: bool = any(w in question for w in self.data_keywords)
        return has_marker and has_data_word

    def _has_recommend_intent(self, question: str) -> bool:
        """判断是否有推荐意图"""
        return any(k in question for k in self.recommend_keywords)

    def route(self, question: str, context: Optional[Dict[str, Any]] = None) -> str:
        """单意图路由：返回最佳 workflow 类型"""
        start = time.time()
        candidates: List[Tuple[str, float]] = self.route_candidates(question, context)
        result = candidates[0][0] if candidates else WorkflowType.CHAT
        _record_router_decision(result, "keyword_only")
        _record_router_latency("keyword_only", time.time() - start)
        return result

    def route_candidates(self, question: str, context: Optional[Dict[str, Any]] = None) -> List[Tuple[str, float]]:
        """多候选路由：返回所有可能的 workflow 及其置信度"""
        ctx: Dict[str, Any] = context or {}
        candidates: List[Tuple[str, float]] = []

        # video_qa：
        # - 有 video_id 且命中强视频词 → 高置信度 1.0
        # - 无 video_id 但命中强视频词（如「这个视频讲了什么」）→ 中置信度 0.6。
        #   否则演示第一句「这个视频讲了什么」会因前端不传 video_id 而落到 chat，
        #   拿到泛泛客服回答而非视频问答（再引导用户提供视频）。
        if ctx.get("video_id") and self._is_about_current_video(question):
            candidates.append((WorkflowType.VIDEO_QA, 1.0))
        elif self._is_about_current_video(question):
            candidates.append((WorkflowType.VIDEO_QA, 0.6))

        if self._is_personal_data_query(question):
            candidates.append((WorkflowType.USER_DATA, 0.9))

        if self._has_recommend_intent(question):
            candidates.append((WorkflowType.RECOMMEND, 0.85))

        # Only add CHAT as fallback when nothing else matched
        if not candidates:
            candidates.append((WorkflowType.CHAT, 0.5))

        seen: set = set()
        unique: List[Tuple[str, float]] = []
        for wf, conf in candidates:
            if wf not in seen:
                seen.add(wf)
                unique.append((wf, conf))

        if not unique:
            unique.append((WorkflowType.CHAT, 0.5))

        return unique

    def hybrid_route(self, question: str, context: Optional[Dict[str, Any]] = None) -> str:
        """两阶段融合路由：返回获胜意图（兼容旧调用方）。"""
        return self.hybrid_route_full(question, context).workflow_type

    def hybrid_route_full(self, question: str, context: Optional[Dict[str, Any]] = None) -> RouteDecision:
        """两阶段融合路由（带问题级缓存）。

        相同 (question, video_id) 在 TTL 内直接复用决策，避免重复问题重复走
        embedding/LLM 裁决（LLM 慢且烧配额）。
        """
        ctx = context or {}
        cache_key = f"{question}::{(ctx.get('video_id') or '')}"

        now = time.time()
        with self._route_cache_lock:
            cached = self._route_cache.get(cache_key)
            if cached is not None:
                ts, decision = cached
                if now - ts < self._route_cache_ttl():
                    self._route_cache.move_to_end(cache_key)
                    return decision
                self._route_cache.pop(cache_key, None)

        decision = self._hybrid_route_full_impl(question, context)

        with self._route_cache_lock:
            self._route_cache[cache_key] = (now, decision)
            if len(self._route_cache) > self._route_cache_max():
                self._route_cache.popitem(last=False)
        return decision

    def _hybrid_route_full_impl(self, question: str, context: Optional[Dict[str, Any]] = None) -> RouteDecision:
        """两阶段融合路由（无缓存，实际计算）。

        阶段一（共识检测）：关键词 Top-1 与语义 Top-1 一致 → 直接返回
        阶段二（分歧裁决）：不一致时 → LLM 裁决，LLM 结果直接覆盖

        置信度是真实信号，不是拍脑袋常数：
        - 共识路径：max(关键词强度, 语义余弦归一化分)
        - LLM 裁决：max(语义, 关键词, 0.7)（LLM 兜底确认）
        - 纯关键词（embedding 不可用）：关键词强度

        上下文信号：
        - video_id + 没有排除关键词 → video_qa 获得 0.5 上下文加分
        - video_id + 明确排除关键词 → 不额外加分（排除规则优先）
        """
        ctx = context or {}
        start_time = time.time()
        keyword_dict = dict(self.route_candidates(question, context))
        semantic_dict = self._semantic_scores(question)

        if ctx.get("video_id"):
            if not any(k in question for k in self.video_exclude):
                has_video_kw = self._is_about_current_video(question)
                if has_video_kw:
                    keyword_dict[WorkflowType.VIDEO_QA] = max(
                        keyword_dict.get(WorkflowType.VIDEO_QA, 0.0), 1.0
                    )
                else:
                    keyword_dict[WorkflowType.VIDEO_QA] = max(
                        keyword_dict.get(WorkflowType.VIDEO_QA, 0.0), 0.5
                    )

        CONFIDENCE_GATE = 0.3

        kw_top = max(keyword_dict, key=keyword_dict.get) if keyword_dict else WorkflowType.CHAT
        sem_top = max(semantic_dict, key=semantic_dict.get) if semantic_dict else WorkflowType.CHAT

        kw_top_val = keyword_dict.get(kw_top, 0.0)
        sem_top_val = semantic_dict.get(sem_top, 0.0)

        # Normalize semantic scores from [-1, 1] to [0, 1] for fair comparison
        sem_top_val_norm = (sem_top_val + 1) / 2
        kw_top_val_norm = kw_top_val

        # embedding 不可用 → 纯关键词路径（无语义分差）
        if not semantic_dict:
            conf = min(max(kw_top_val_norm, 0.0), 1.0)
            if conf < CONFIDENCE_GATE:
                logger.info(f"keyword_low_conf: {kw_top} ({conf:.2f}), fallback to chat")
                _record_router_decision(WorkflowType.CHAT, "keyword_low_conf")
                _record_router_latency("keyword_only", time.time() - start_time)
                return RouteDecision(WorkflowType.CHAT, conf, "keyword_low_conf")
            logger.info(f"keyword_route: {kw_top} (kw={kw_top_val:.2f})")
            _record_router_decision(kw_top, "keyword_only")
            _record_router_latency("keyword_only", time.time() - start_time)
            return RouteDecision(kw_top, conf, "keyword_only")

        if kw_top == sem_top:
            best_signal = kw_top_val_norm if kw_top_val_norm >= sem_top_val_norm else sem_top_val_norm
            if best_signal < CONFIDENCE_GATE:
                logger.info(f"low_confidence_consensus: {kw_top} ({best_signal:.2f}), fallback to chat")
                _record_router_decision(WorkflowType.CHAT, "consensus_low_conf")
                _record_router_latency("consensus", time.time() - start_time)
                return RouteDecision(WorkflowType.CHAT, best_signal, "consensus_low_conf")
            logger.info(f"consensus_route: {kw_top} (kw={kw_top_val:.2f}, sem={sem_top_val:.2f})")
            _record_router_decision(kw_top, "consensus")
            _record_router_latency("consensus", time.time() - start_time)
            return RouteDecision(kw_top, best_signal, "consensus")

        llm_result = self._route_with_llm(question, context)
        if llm_result is not None:
            conf = min(max(max(sem_top_val_norm, kw_top_val_norm), 0.7), 1.0)
            logger.info(f"llm_route: {llm_result} (kw={kw_top}, sem={sem_top}, conf={conf:.2f})")
            _record_router_decision(llm_result, "llm")
            _record_router_latency("llm", time.time() - start_time)
            return RouteDecision(llm_result, conf, "llm")

        final = kw_top if kw_top_val >= sem_top_val else sem_top
        best_signal = max(kw_top_val_norm, sem_top_val_norm)
        if best_signal < CONFIDENCE_GATE:
            logger.info(f"low_confidence_fallback: {final} ({best_signal:.2f}), default to chat")
            _record_router_decision(WorkflowType.CHAT, "fallback_low_conf")
            _record_router_latency("fallback", time.time() - start_time)
            return RouteDecision(WorkflowType.CHAT, best_signal, "fallback_low_conf")
        logger.info(f"fallback_route: {final} (kw={kw_top}, sem={sem_top})")
        _record_router_decision(final, "fallback")
        _record_router_latency("fallback", time.time() - start_time)
        return RouteDecision(final, best_signal, "fallback")

    def _route_with_llm(self, question: str, context: dict = None) -> Optional[str]:
        """
        LLM 裁决意图分类。返回意图名称或 None（不可用 / 出错）。

        返回 None 而不是 "" —— 调用方用 is None 判断更明确，
        避免空字符串 magic value 与合法分类混淆。
        """
        try:
            from app.tools.llm_tools import LLM_tools
            from app.tools.tool_registry import get_router_tool_schemas
            ROUTER_TOOLS = get_router_tool_schemas()

            messages = [
                {"role": "system", "content": (
                    f"你是一个意图分类器。判断用户提问属于哪个类型，只返回以下四种之一：\n\n"
                    f"1. {WorkflowType.VIDEO_QA} — 用户问的是当前视频的内容、讲解、总结（需要结合 video_id 上下文）\n"
                    f"2. {WorkflowType.RECOMMEND} — 用户要求推荐视频、找好看的、问热门内容\n"
                    f"3. {WorkflowType.USER_DATA} — 用户查询自己的数据，如点赞、收藏、播放历史（含[我]字）\n"
                    f"4. {WorkflowType.CHAT} — 闲聊、平台介绍、功能询问、其他无法归类的\n\n"
                    f"规则：\n"
                    f"- 如果问题同时匹配多个类型，按以上顺序取第一个\n"
                    f"- 不确定时返回 {WorkflowType.CHAT}\n"
                    f"- 只输出意图名称，不要解释"
                )},
                {"role": "user", "content": question}
            ]

            result = LLM_tools.chat_with_tools_router(messages, ROUTER_TOOLS)
            if result and result.get("tool_call"):
                intent = result.get("arguments", {}).get("intent_type", "")
                if intent in WorkflowType.all():
                    return intent

            if result and result.get("content"):
                resp = result["content"].strip().lower()
                for t in WorkflowType.all():
                    if t in resp:
                        return t
        except Exception as e:
            logger.warning(f"LLM 路由失败: {e}")
        return None
