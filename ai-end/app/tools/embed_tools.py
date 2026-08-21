"""
Embedding 模型加载与编码（独立模块）。

从 llm_tools.py 拆出，职责单一：
- 按 FastEmbed → sentence-transformers → hash 三级降级加载模型
- 提供 embed / warmup_embedding 入口
- embedding_is_fallback 标志：hash 兜底时语义路由/检索自动降级纯关键词

对外 API（LLM_tools 转发或直接使用）：
  get_embed_model()
  embed(texts) -> Optional[List[List[float]]]
  warmup_embedding(timeout=30) -> bool
  embedding_is_fallback: bool
"""
import hashlib
import logging
import threading
from typing import List, Optional

from app.config import settings

logger = logging.getLogger(__name__)


class _HashEmbedder:
    """轻量哈希 embedding 兜底：语义不可用时保底，不用于真实语义匹配。"""

    def __init__(self, dim: int = 384):
        self.dim = dim

    def encode(self, texts: List[str]) -> List[List[float]]:
        result = []
        for text in texts:
            vec = [0.0] * self.dim
            for i, ch in enumerate(text):
                h = int(hashlib.md5((ch + str(i)).encode("utf-8")).hexdigest()[:8], 16)
                vec[h % self.dim] += 1.0
            norm = sum(v * v for v in vec) ** 0.5
            if norm > 0:
                vec = [v / norm for v in vec]
            result.append(vec)
        return result


# ─── 模型单例 + 降级标志 ───
_embed_model = None
_embed_lock = threading.Lock()
# True 表示当前 embedding 不是真实语义模型（hash 兜底），路由/检索应降级纯关键词
embedding_is_fallback = False


def _reset_for_tests() -> None:
    """测试专用：重置模型与降级标志。"""
    global _embed_model, embedding_is_fallback
    _embed_model = None
    embedding_is_fallback = False


def get_embed_model():
    """按 FastEmbed → sentence-transformers → hash 三级加载 embedding 模型。"""
    global _embed_model, embedding_is_fallback
    if _embed_model is not None:
        return _embed_model
    with _embed_lock:
        if _embed_model is not None:
            return _embed_model
        # 1. FastEmbed（ONNX 轻量，无需 PyTorch，本地模型）
        _fail_fastembed: Optional[str] = None
        try:
            from app.tools.fastembed_embeddings import FastEmbedEmbeddings
            _embed_model = FastEmbedEmbeddings()
            embedding_is_fallback = False
            logger.info("Embedding 模型加载完成（FastEmbed / ONNX）")
            return _embed_model
        except Exception as e:
            _fail_fastembed = f"{type(e).__name__}: {e}"
            logger.debug(f"加载 FastEmbed 失败: {e}")
        # 2. sentence-transformers（有 PyTorch 环境时）
        _fail_st: Optional[str] = None
        try:
            from sentence_transformers import SentenceTransformer
            _embed_model = SentenceTransformer(settings.embed_model_name)
            embedding_is_fallback = False
            logger.info("Embedding 模型加载完成（sentence-transformers）")
            return _embed_model
        except Exception as e:
            _fail_st = f"{type(e).__name__}: {e}"
            logger.debug(f"加载 sentence_transformers 失败: {e}")
        # 3. Hash fallback（兜底）
        embedding_is_fallback = True
        logger.warning(
            "Embedding 降级到 hash-based fallback：语义检索/语义路由将自动降级为纯关键词"
            + (f"。FastEmbed 失败: {_fail_fastembed}" if _fail_fastembed else "")
            + (f"。sentence-transformers 失败: {_fail_st}" if _fail_st else "")
        )
        _embed_model = _HashEmbedder(dim=384)
    return _embed_model


def embed(texts: List[str]) -> Optional[List[List[float]]]:
    """对文本列表做 embedding；模型不可用时返回 None（调用方降级纯关键词）。

    统一返回纯 Python list（list[list[float]]），不返回 numpy——调用方
    （router._get_embedding 的 `if not vecs`、cosine 计算）依赖 list 语义。
    """
    try:
        model = get_embed_model()
        if model is None:
            return None
        vecs = model.encode(texts)
        return [list(v) for v in vecs]
    except Exception as e:
        logger.warning(f"Embedding 计算失败: {e}")
        return None


def warmup_embedding(timeout: float = 30.0) -> bool:
    """
    启动期预热 Embedding 模型。

    收益：避免首请求冷启动（模型加载 + warmup 通常 5-15s）。
    失败不抛异常——预热失败应让首请求重试，而不是阻塞启动。

    timeout：超过这个时间就放弃预热（首请求仍会触发加载）。
    """
    try:
        import signal

        class _TimeoutError(Exception):
            pass

        def _alarm_handler(signum, frame):
            raise _TimeoutError("warmup timeout")

        old_handler = signal.signal(signal.SIGALRM, _alarm_handler)
        signal.alarm(int(timeout))
        try:
            model = get_embed_model()
            if model is None:
                logger.warning("Embedding 预热跳过：模型加载失败")
                return False
            _ = model.encode(["warmup"])
            logger.info("Embedding 模型预热完成")
            return True
        except _TimeoutError:
            logger.warning(f"Embedding 预热超时（>{timeout}s），跳过；首请求会触发加载")
            return False
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)
    except Exception as e:
        # signal 在非 Unix 系统不可用——降级到不带超时
        logger.debug(f"Embedding 预热（无超时模式）异常: {e}")
        try:
            model = get_embed_model()
            if model is None:
                return False
            _ = model.encode(["warmup"])
            logger.info("Embedding 模型预热完成（无超时模式）")
            return True
        except Exception as e2:
            logger.warning(f"Embedding 预热失败: {e2}")
            return False
