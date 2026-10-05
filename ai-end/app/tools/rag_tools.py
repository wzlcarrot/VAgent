import logging
import re
import threading
from typing import Any, Dict, List, Optional

from psycopg2.extras import RealDictCursor

from app.tools.db import get_global_pool

logger = logging.getLogger(__name__)


def _has_chinese(text: str) -> bool:
    return any('\u4e00' <= c <= '\u9fff' for c in text)


def _bm25_query_text(query: str) -> str:
    """清洗成 BM25 查询串：去掉 Tantivy 特殊符号，保留中英文与数字，避免语法解析报错。"""
    return re.sub(r"[^\w\u4e00-\u9fff]+", " ", query or "", flags=re.UNICODE).strip()


def _safe_float(score: Any, default: float = 0.0) -> float:
    """检索分可能是 Decimal / None；None 不能丢给 float()。"""
    if score is None:
        return default
    try:
        return float(score)
    except (TypeError, ValueError):
        return default


def _bm25_to_unit(score: Any) -> float:
    """BM25 原始分（0~∞）单调压到 (0,1)，便于与余弦相似度混排、过证据闸门。"""
    v = _safe_float(score, 0.0)
    return v / (v + 1.0) if v > 0 else 0.0


def _char_bigrams(text: str) -> set:
    chars = text.strip().lower()
    if not chars:
        return set()
    return {chars[i:i+2] for i in range(len(chars) - 1)}


# ─── 平台 FAQ 内存缓存 ───
# 启动时从 platform_docs 表加载，fallback 时也用这份做兜底
# 缓存过期时间 5 分钟，定期刷新（运营可在 DB 改完自动生效）
_FAQ_CACHE: List[Dict[str, Any]] = []
_FAQ_CACHE_LOCK = threading.Lock()
_FAQ_CACHE_LOADED_AT: float = 0.0
_FAQ_CACHE_TTL: float = 300.0


def _load_faq_cache_from_db() -> List[Dict[str, Any]]:
    """从 platform_docs 表加载 FAQ/GUIDE 文档到内存"""
    try:
        pool = get_global_pool()
        if pool is None:
            return []
        conn = pool.getconn()
        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("""
                SELECT title, content, type FROM platform_docs
                WHERE type IN ('faq', 'guide')
                ORDER BY id ASC
            """)
            rows = cursor.fetchall()
            cursor.close()
            return [
                {"title": r.get("title", ""), "content": r.get("content", ""), "type": r.get("type", "faq")}
                for r in rows
            ]
        finally:
            pool.putconn(conn)
    except Exception as e:
        logger.debug(f"从 DB 加载 FAQ 失败: {e}")
        return []


def get_faq_cache(refresh: bool = False) -> List[Dict[str, Any]]:
    """
    获取 FAQ 缓存（带 TTL）。

    首次调用时从 DB 加载；TTL 过期后自动重载；
    强制 refresh=True 用于运营手动刷新。
    """
    global _FAQ_CACHE, _FAQ_CACHE_LOADED_AT
    import time
    now = time.time()
    with _FAQ_CACHE_LOCK:
        if refresh or not _FAQ_CACHE or (now - _FAQ_CACHE_LOADED_AT) > _FAQ_CACHE_TTL:
            loaded = _load_faq_cache_from_db()
            if loaded:
                _FAQ_CACHE = loaded
                _FAQ_CACHE_LOADED_AT = now
            elif not _FAQ_CACHE:
                _FAQ_CACHE = list(PLATFORM_FAQ_FALLBACK)
                _FAQ_CACHE_LOADED_AT = now
        return list(_FAQ_CACHE)


class RAGTools:
    _available: Optional[bool] = None

    @classmethod
    def _is_available(cls) -> bool:
        if cls._available is not None:
            return cls._available
        try:
            pool = get_global_pool()
            if pool is None:
                cls._available = False
                return False
            conn = pool.getconn()
            pool.putconn(conn)
            cls._available = True
            return True
        except Exception as e:
            logger.warning(f"PostgreSQL 不可用: {e}")
            cls._available = False
            return False

    @classmethod
    def _reset_available(cls):
        cls._available = None

    @classmethod
    def retrieve_knowledge(cls, query: str, top_k: int = 5,
                           video_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """BM25 全文搜索（ParadeDB），降级到 PG tsvector；可选 video_id 限定当前视频检索"""
        if not cls._is_available():
            return []
        if video_id:
            return cls._retrieve_video_scoped_knowledge(query, top_k, video_id)
        try:
            pool = get_global_pool()
            if pool is None:
                return []
            conn = pool.getconn()
            try:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                try:
                    cursor.execute("SET LOCAL statement_timeout = '2000'")
                    cursor.execute("""
                        SELECT video_id, video_name, introduction, paradedb.score() as score
                        FROM video_info
                        WHERE video_info @@@ %s
                        ORDER BY score DESC
                        LIMIT %s
                    """, (query, top_k))
                    rows = cursor.fetchall()
                    cursor.close()
                    return [{
                        "content": r.get("introduction") or r.get("video_name", ""),
                        "video_id": r["video_id"],
                        "video_name": r.get("video_name", ""),
                        "block_type": "introduction",
                        "score": _safe_float(r.get("score", 0))
                    } for r in rows]
                except Exception:
                    cursor.close()
                    conn.rollback()
                    cursor2 = conn.cursor(cursor_factory=RealDictCursor)
                    try:
                        if _has_chinese(query):
                            cursor2.execute("""
                                SELECT video_id, video_name, introduction,
                                       similarity(coalesce(video_name,'') || ' ' || coalesce(introduction,''), %s) as score
                                FROM video_info
                                WHERE similarity(coalesce(video_name,'') || ' ' || coalesce(introduction,''), %s) > 0.1
                                ORDER BY score DESC
                                LIMIT %s
                            """, (query, query, top_k))
                        else:
                            cursor2.execute("""
                                SELECT video_id, video_name, introduction,
                                       ts_rank(to_tsvector('simple', coalesce(video_name,'') || ' ' || coalesce(introduction,'')), plainto_tsquery('simple', %s)) as score
                                FROM video_info
                                WHERE to_tsvector('simple', coalesce(video_name,'') || ' ' || coalesce(introduction,'')) @@ plainto_tsquery('simple', %s)
                                ORDER BY score DESC
                                LIMIT %s
                            """, (query, query, top_k))
                        rows = cursor2.fetchall()
                        return [{
                            "content": r.get("introduction") or r.get("video_name", ""),
                            "video_id": r["video_id"],
                            "video_name": r.get("video_name", ""),
                            "block_type": "introduction",
                            "score": _safe_float(r.get("score", 0))
                        } for r in rows]
                    finally:
                        cursor2.close()
            finally:
                pool.putconn(conn)
        except Exception as e:
            logger.error(f"知识库检索失败: {e}")
            return []

    @classmethod
    def _retrieve_video_scoped_knowledge(cls, query: str, top_k: int,
                                         video_id: str) -> List[Dict[str, Any]]:
        """限定单视频的 keyword 召回：BM25 优先，降级 pg_trgm/tsvector；补 video_info 元数据。"""
        if not query or not video_id:
            return []
        try:
            pool = get_global_pool()
            if pool is None:
                return []
            conn = pool.getconn()
            try:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                rows: List[Dict[str, Any]] = []
                used_bm25 = False
                bm25_text = _bm25_query_text(query)
                # 首选 ParadeDB BM25（当前视频关键词路）
                if bm25_text:
                    try:
                        cursor.execute("SET LOCAL statement_timeout = '2000'")
                        cursor.execute("""
                            SELECT video_id, file_id, file_index, block_type, block_content, start_s, end_s,
                                   paradedb.score(id) AS score
                            FROM video_vector_block
                            WHERE video_id = %s
                              AND block_content @@@ %s
                            ORDER BY score DESC
                            LIMIT %s
                        """, (video_id, bm25_text, top_k))
                        rows = cursor.fetchall() or []
                        used_bm25 = bool(rows)
                        cursor.execute("SET LOCAL statement_timeout = 0")
                    except Exception as e:
                        conn.rollback()
                        rows = []
                        logger.debug("当前视频 BM25 召回失败，降级 pg_trgm/tsvector: %s", e)

                if not rows:
                    # 降级：pg_trgm（中文）/ tsvector（其它），BM25 索引缺失或不可用时兜底
                    try:
                        if _has_chinese(query):
                            cursor.execute("""
                                SELECT video_id, file_id, file_index, block_type, block_content, start_s, end_s,
                                       similarity(block_content, %s) AS score
                                FROM video_vector_block
                                WHERE video_id = %s
                                  AND similarity(block_content, %s) > 0.05
                                ORDER BY score DESC
                                LIMIT %s
                            """, (query, video_id, query, top_k))
                        else:
                            cursor.execute("""
                                SELECT video_id, file_id, file_index, block_type, block_content, start_s, end_s,
                                       ts_rank(
                                           to_tsvector('simple', coalesce(block_content, '')),
                                           plainto_tsquery('simple', %s)
                                       ) AS score
                                FROM video_vector_block
                                WHERE video_id = %s
                                  AND to_tsvector('simple', coalesce(block_content, ''))
                                      @@ plainto_tsquery('simple', %s)
                                ORDER BY score DESC
                                LIMIT %s
                            """, (query, video_id, query, top_k))
                        rows = cursor.fetchall() or []
                    except Exception:
                        conn.rollback()

                # BM25 原始分压到 (0,1)，与余弦相似度同量纲，便于混排与证据闸门
                if used_bm25:
                    for r in rows:
                        if isinstance(r, dict):
                            r["score"] = _bm25_to_unit(r.get("score"))

                if not rows:
                    cursor.execute("""
                        SELECT video_id, video_name, introduction
                        FROM video_info
                        WHERE video_id = %s
                    """, (video_id,))
                    info = cursor.fetchone()
                    if info:
                        text = " ".join(
                            p for p in [
                                info.get("video_name") or "",
                                info.get("introduction") or "",
                            ] if p
                        ).strip()
                        if text:
                            rows = [{
                                "video_id": info["video_id"],
                                "block_type": "introduction",
                                "block_content": text,
                                "score": 0.5,
                                "video_name": info.get("video_name", ""),
                            }]
                cursor.close()
                return [{
                    "content": r.get("block_content") or r.get("introduction") or r.get("video_name", ""),
                    "video_id": r["video_id"],
                    "video_name": r.get("video_name", ""),
                    "block_type": r.get("block_type", "block"),
                    "score": _safe_float(r.get("score", 0)),
                    "start_s": r.get("start_s"),
                    "end_s": r.get("end_s"),
                    "file_id": r.get("file_id"),
                    "file_index": r.get("file_index"),
                } for r in rows if r.get("block_content") or r.get("introduction") or r.get("video_name")]
            finally:
                pool.putconn(conn)
        except Exception as e:
            logger.error(f"当前视频 keyword 检索失败 video_id={video_id}: {e}")
            return []

    @classmethod
    def retrieve_platform_docs(cls, query: str, top_k: int = 3) -> List[Dict[str, Any]]:
        """
        平台文档搜索。

        优化：内存缓存优先（启动时已加载），避免每次打 PG。
        PG ts_rank 改为纯内存关键词匹配 + tsvector-like 评分。
        FAQ 表通常 < 100 条，内存匹配足够快。
        """
        try:
            faq_docs = get_faq_cache()
            if faq_docs:
                query_lower = query.lower()
                if _has_chinese(query_lower):
                    query_terms = _char_bigrams(query_lower)
                    def _count_hits(text: str) -> int:
                        text_lower = text.lower()
                        text_bigrams = _char_bigrams(text_lower)
                        return len(query_terms & text_bigrams) if text_bigrams else 0
                else:
                    query_terms = set(query_lower.split())
                    def _count_hits(text: str) -> int:
                        text_lower = text.lower()
                        return sum(1 for t in query_terms if t in text_lower)

                scored = []
                for doc in faq_docs:
                    text = (doc.get("title", "") + " " + doc.get("content", "")).lower()
                    if not text.strip():
                        continue
                    hit_count = _count_hits(text) if query_terms else 0
                    if hit_count > 0:
                        score = hit_count / max((len(query_terms) if isinstance(query_terms, set) else len(query_terms)), 1)
                        scored.append({
                            "title": doc.get("title", ""),
                            "content": doc.get("content", ""),
                            "type": doc.get("type", "doc"),
                            "score": float(score),
                        })
                scored.sort(key=lambda x: x["score"], reverse=True)
                if scored:
                    return scored[:top_k]
        except Exception as e:
            logger.debug(f"内存 platform_docs 检索失败，降级到 PG: {e}")

        # PG 兜底：DB 表比缓存更全（含运营后续新增但还没热加载的）
        try:
            pool = get_global_pool()
            if pool is None:
                return _search_faq(query, top_k)
            conn = pool.getconn()
            try:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                cursor.execute("""
                    SELECT title, content, type,
                           ts_rank(to_tsvector('simple', coalesce(title,'') || ' ' || coalesce(content,'')), plainto_tsquery('simple', %s)) as score
                    FROM platform_docs
                    WHERE to_tsvector('simple', coalesce(title,'') || ' ' || coalesce(content,'')) @@ plainto_tsquery('simple', %s)
                    ORDER BY score DESC
                    LIMIT %s
                """, (query, query, top_k))
                rows = cursor.fetchall()
                cursor.close()
            finally:
                pool.putconn(conn)
            if rows:
                # PG 命中后顺便刷新缓存（运营刚加的 doc）
                try:
                    refresh_faq_cache()
                except Exception:
                    pass
                return [{
                    "title": r.get("title", ""),
                    "content": r.get("content", ""),
                    "type": r.get("type", "doc"),
                    "score": float(r.get("score", 0))
                } for r in rows]
        except Exception as e:
            logger.debug(f"PG platform_docs 查询失败，降级到内置 FAQ: {e}")

        return _search_faq(query, top_k)

    @classmethod
    def vector_search(cls, query_vector: List[float], top_k: int = 10,
                      video_id: Optional[str] = None) -> List[Dict[str, Any]]:
        try:
            pool = get_global_pool()
            if pool is None:
                return []
            conn = pool.getconn()
            try:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                vector_str = "[" + ",".join(str(v) for v in query_vector) + "]"
                if video_id:
                    cursor.execute("""
                        SELECT video_id, file_id, file_index, block_type, block_content, start_s, end_s,
                               (1.0 - (content_vector <=> %s::vector))
                                   * COALESCE(block_weight, 1.0) AS score
                        FROM video_vector_block
                        WHERE video_id = %s
                          AND content_vector IS NOT NULL
                        ORDER BY score DESC
                        LIMIT %s
                    """, (vector_str, video_id, top_k))
                    rows = cursor.fetchall()
                    cursor.close()
                    return [{
                        "content": r.get("block_content", ""),
                        "video_id": r["video_id"],
                        "video_name": "",
                        "block_type": r.get("block_type", "vector"),
                        "score": _safe_float(r.get("score", 0)),
                        "start_s": r.get("start_s"),
                        "end_s": r.get("end_s"),
                        "file_id": r.get("file_id"),
                        "file_index": r.get("file_index"),
                    } for r in rows if r.get("block_content")]
                cursor.execute("""
                    WITH weighted AS (
                        SELECT video_id,
                            COALESCE(SUM(
                                CASE WHEN block_type LIKE 'title%%' OR block_type LIKE 'tags%%' OR block_type LIKE 'introduction%%'
                                THEN (1.0 - (content_vector <=> %s::vector)) * block_weight
                                END
                            ), 0) AS total_score
                        FROM video_vector_block
                        GROUP BY video_id
                    )
                    SELECT w.video_id, w.total_score, v.video_name, v.introduction
                    FROM weighted w
                    LEFT JOIN video_info v ON w.video_id = v.video_id
                    WHERE w.total_score > 0
                    ORDER BY w.total_score DESC
                    LIMIT %s
                """, (vector_str, top_k))
                rows = cursor.fetchall()
                cursor.close()
            finally:
                pool.putconn(conn)
            return [{
                "content": r.get("introduction") or r.get("video_name", ""),
                "video_id": r["video_id"],
                "video_name": r.get("video_name", ""),
                "block_type": "vector",
                "score": _safe_float(r.get("total_score", 0))
            } for r in rows]
        except Exception as e:
            logger.error(f"向量搜索失败: {e}")
            return []

    @classmethod
    def index_document(cls, video_id: str, block_type: str, content: str,
                       block_weight: float = 1.0,
                       duration_s: Optional[float] = None) -> bool:
        """
        索引一段文本到 video_vector_block。

        改进（接入"Java 上传视频 → Python 生成索引"链路前必须修）：
        - 每个 chunk 独立 embedding（原来整段一个向量，块与向量错配）
        - 索引前清理该视频该类型的旧块（幂等，重复索引不残留）
        - block_type 存 `{base}_{i}` 带序号，检索端用 LIKE 匹配
        - block_weight 供 vector_search 加权（title 1.0 / tags 0.5 / intro 0.3）
        - start_s/end_s：有 duration 时对 introduction 按块序比例估计，供 citations 跳转

        Args:
            video_id: 视频 ID
            block_type: 基础类型（title / tags / introduction）
            content: 待索引文本
            block_weight: 检索加权（写入列，由 vector_search 消费）
            duration_s: 视频时长（秒）；缺省则不写时间轴
        """
        from app.tools.chunker import chunk_document
        from app.tools.llm_tools import LLM_tools
        chunks = chunk_document(content)
        if not chunks:
            return False

        # 对每个 chunk 独立 embedding（返回 None 表示失败）
        try:
            embeddings = LLM_tools.embed(chunks)
        except Exception as e:
            logger.error(f"索引 embedding 失败: {e}")
            return False
        if not embeddings or len(embeddings) != len(chunks):
            logger.error("索引 embedding 数量不匹配")
            return False

        n = len(chunks)
        dur = float(duration_s) if duration_s and float(duration_s) > 0 else None

        pool = get_global_pool()
        if pool is None:
            return False
        conn = pool.getconn()
        try:
            cursor = conn.cursor()
            # 清理该视频该类型的旧块（幂等）
            cursor.execute(
                "DELETE FROM video_vector_block WHERE video_id = %s AND block_type LIKE %s",
                (video_id, f"{block_type}%"),
            )
            for i, (chunk_text, vec) in enumerate(zip(chunks, embeddings, strict=False)):
                vector_str = "[" + ",".join(str(v) for v in vec) + "]"
                start_s, end_s = cls._estimate_chunk_window(block_type, i, n, dur)
                cursor.execute("""
                    INSERT INTO video_vector_block
                        (video_id, block_type, block_content, content_vector, block_weight, start_s, end_s)
                    VALUES (%s, %s, %s, %s::vector, %s, %s, %s)
                """, (video_id, f"{block_type}_{i}", chunk_text, vector_str, block_weight, start_s, end_s))
            conn.commit()
            cursor.close()
            logger.info(f"已索引 {video_id} 的 {block_type} 块（{len(chunks)} 个 chunk）")
            return True
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.error(f"文档索引失败: {e}")
            return False
        finally:
            pool.putconn(conn)

    @staticmethod
    def _estimate_chunk_window(
        block_type: str, index: int, total: int, duration_s: Optional[float],
    ) -> tuple:
        """无 ASR 时的时间窗估计：title/tags→0；introduction 按块序映射到片长。"""
        if duration_s is None or duration_s <= 0 or total <= 0:
            if block_type == "title":
                return 0.0, None
            return None, None
        if block_type in ("title", "tags"):
            return 0.0, min(30.0, duration_s)
        # introduction：均匀铺开片长（预留末尾 5%），ASR 落地后可替换为真实时间戳
        span = duration_s * 0.95
        start = round((index / total) * span, 1)
        end = round(((index + 1) / total) * span, 1)
        return start, end

    @classmethod
    def delete_subtitle_blocks(cls, video_id: str) -> None:
        """删除该视频所有 subtitle 向量块（重建索引前清理）。"""
        if not video_id:
            return
        pool = get_global_pool()
        if pool is None:
            return
        conn = pool.getconn()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM video_vector_block WHERE video_id = %s AND block_type LIKE %s",
                (video_id, "subtitle%"),
            )
            conn.commit()
            cursor.close()
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning("清理字幕向量块失败 video_id=%s: %s", video_id, e)
        finally:
            pool.putconn(conn)

    @classmethod
    def index_subtitle_segments(
        cls,
        video_id: str,
        segments: List[Dict[str, Any]],
        *,
        file_id: Optional[str] = None,
        file_index: int = 1,
        block_weight: float = 0.85,
    ) -> bool:
        """将带真实时间轴的字幕段写入 video_vector_block（block_type=subtitle_{file}_{i}）。"""
        from app.tools.llm_tools import LLM_tools

        if not video_id or not segments:
            return False
        try:
            f_index = int(file_index)
        except (TypeError, ValueError):
            f_index = 1
        f_id = (str(file_id).strip() if file_id else None) or None

        texts: List[str] = []
        meta: List[tuple] = []
        for seg in segments:
            if not isinstance(seg, dict):
                continue
            text = (seg.get("text") or "").strip()
            if not text:
                continue
            try:
                start_s = float(seg["start_s"])
            except (TypeError, ValueError, KeyError):
                continue
            end_s = seg.get("end_s")
            try:
                end_s = float(end_s) if end_s is not None else None
            except (TypeError, ValueError):
                end_s = None
            texts.append(text)
            meta.append((start_s, end_s))

        if not texts:
            return False

        try:
            embeddings = LLM_tools.embed(texts)
        except Exception as e:
            logger.error(f"字幕 embedding 失败: {e}")
            return False
        if not embeddings or len(embeddings) != len(texts):
            return False

        pool = get_global_pool()
        if pool is None:
            return False
        conn = pool.getconn()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM video_vector_block WHERE video_id = %s AND block_type LIKE %s",
                (video_id, f"subtitle_{f_index}_%"),
            )
            for i, (text, vec, (start_s, end_s)) in enumerate(
                zip(texts, embeddings, meta, strict=False),
            ):
                vector_str = "[" + ",".join(str(v) for v in vec) + "]"
                cursor.execute(
                    """
                    INSERT INTO video_vector_block
                        (video_id, file_id, file_index, block_type, block_content,
                         content_vector, block_weight, start_s, end_s)
                    VALUES (%s, %s, %s, %s, %s, %s::vector, %s, %s, %s)
                    """,
                    (video_id, f_id, f_index, f"subtitle_{f_index}_{i}",
                     text, vector_str, block_weight, start_s, end_s),
                )
            conn.commit()
            cursor.close()
            logger.info(
                "已索引 %s 字幕块 file_index=%s count=%d", video_id, f_index, len(texts),
            )
            return True
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.error(f"字幕索引失败: {e}")
            return False
        finally:
            pool.putconn(conn)

    @classmethod
    def _video_context(cls, video_id: str) -> str:
        """拼出视频标题/标签/简介，供字幕纠错做上下文。"""
        try:
            from app.tools import VideoTools
            v = VideoTools.get_video_info(video_id)
        except Exception:
            return ""
        if not v:
            return ""
        parts: List[str] = []
        name = getattr(v, "videoName", None)
        if name:
            parts.append(f"标题：{name}")
        tags = getattr(v, "tags", None)
        if tags:
            parts.append(f"标签：{tags}")
        intro = (getattr(v, "introduction", None) or "").strip()
        if intro:
            parts.append(f"简介：{intro[:200]}")
        return "\n".join(parts)

    @classmethod
    def index_video_subtitles(cls, video_id: str) -> Dict[str, Any]:
        """逐分片 ASR → PostgreSQL 原始段 → 合并 → subtitle_* 向量块。

        多分片（video_info_file 多行）时按 file 分别转写与存储，字幕和向量块都带
        file_id/file_index，播放器切集时按 file 读取，引用也能定位到分片。
        """
        from app.config import settings
        from app.services.video_asr import merge_segments_for_index, transcribe_media_file
        from app.services.video_media_paths import list_video_files, resolve_media_path_for_file
        from app.services.video_subtitle_storage import (
            load_subtitle_segments,
            save_subtitle_segments,
        )

        result: Dict[str, Any] = {
            "indexed": False,
            "segment_count": 0,
            "index_block_count": 0,
            "file_count": 0,
            "corrected": False,
        }

        files = list_video_files(video_id)
        if not files:
            # 兼容：没有 video_info_file 记录时，按单文件处理
            files = [{"file_id": None, "file_index": 1, "file_path": ""}]

        context = cls._video_context(video_id)
        cls.delete_subtitle_blocks(video_id)

        any_indexed = False
        reason_set = False
        for f in files:
            f_index = f["file_index"]
            f_id = f["file_id"]
            raw_segments: List[Dict[str, Any]] = []
            corrected = False

            if settings.video_asr_enabled and f["file_path"]:
                media = resolve_media_path_for_file(f["file_path"])
                if media is not None:
                    raw_segments = transcribe_media_file(media)
                    if raw_segments:
                        from app.services.video_subtitle_correction import correct_segments
                        fixed = correct_segments(raw_segments, context=context)
                        if fixed:
                            corrected = fixed != raw_segments
                            raw_segments = fixed
                        save_subtitle_segments(
                            video_id, raw_segments,
                            file_id=f_id, file_index=f_index,
                            source="asr_llm" if corrected else "asr",
                        )

            if not raw_segments:
                stored = load_subtitle_segments(video_id, file_index=f_index)
                raw_segments = [
                    {"text": s["text"], "start_s": s["start_s"], "end_s": s.get("end_s")}
                    for s in stored
                ]

            if not raw_segments:
                continue

            result["segment_count"] += len(raw_segments)
            result["file_count"] += 1
            if corrected:
                result["corrected"] = True

            merged = merge_segments_for_index(
                raw_segments,
                max_gap_s=settings.video_asr_merge_max_gap_s,
                max_chars=settings.video_asr_merge_max_chars,
            )
            if not merged:
                continue
            ok = cls.index_subtitle_segments(
                video_id, merged, file_id=f_id, file_index=f_index,
            )
            if ok:
                any_indexed = True
                result["index_block_count"] += len(merged)
            elif not reason_set:
                result["reason"] = "index_failed"
                reason_set = True

        if not any_indexed and result.get("reason") is None:
            result["reason"] = "asr_empty_or_unavailable"
        result["indexed"] = any_indexed
        return result


    @classmethod
    def index_video(cls, video_id: str) -> Dict[str, Any]:
        """
        索引一条视频（接入"Java 上传视频 → Python 生成索引"链路）。

        查 video_info → 提取 title / tags / introduction → 各自切块 + embedding 写入。
        幂等：重复索引会先清理旧块。返回每部分的索引结果。
        """
        from app.tools import VideoTools
        video = VideoTools.get_video_info(video_id)
        if not video:
            return {"success": False, "video_id": video_id, "error": "视频不存在"}

        # 元数据块不写估算时间轴（避免 citations 误导）；真实时间仅来自 ASR subtitle_*
        parts = {
            "title": (video.videoName or "").strip(),
            "tags": (video.tags or "").strip(),
            "introduction": (video.introduction or "").strip(),
        }
        results = {}
        for part_type, text in parts.items():
            if not text:
                results[part_type] = {"indexed": False, "reason": "无内容"}
                continue
            try:
                ok = cls.index_document(
                    video_id, part_type, text,
                    # 与 vector_search 的加权语义一致：title 最重要，introduction 次要
                    block_weight=1.0 if part_type == "title" else (0.5 if part_type == "tags" else 0.3),
                    duration_s=None,
                )
                results[part_type] = {"indexed": ok}
            except Exception as e:
                results[part_type] = {"indexed": False, "error": str(e)}

        try:
            results["subtitle"] = cls.index_video_subtitles(video_id)
        except Exception as e:
            results["subtitle"] = {"indexed": False, "error": str(e)}

        success = any(r.get("indexed") for r in results.values())
        return {"success": success, "video_id": video_id, "parts": results}
PLATFORM_FAQ_FALLBACK = [
    {"title": "ViewHub 是什么", "content": "ViewHub 是一个视频分享平台，支持视频上传、播放、弹幕互动、评论交流等功能。你可以在这里找到各种有趣的视频内容。", "type": "faq"},
    {"title": "如何注册账号", "content": "点击登录弹窗的「注册」标签，填写邮箱、昵称、密码，通过邮箱验证码完成注册。注册成功后即可正常使用所有功能。", "type": "guide"},
    {"title": "如何登录", "content": "点击页面右上角的「登录」按钮，输入已注册的邮箱和密码即可登录。登录后可以发布视频、点赞收藏、发送弹幕等。", "type": "guide"},
    {"title": "如何发布视频", "content": "登录后点击右上角头像，选择「发布视频」。填写视频标题、简介、标签等信息，上传视频文件后提交。系统会自动转码和处理。", "type": "guide"},
    {"title": "如何点赞和收藏", "content": "在视频播放页面，点击「点赞」按钮可以给视频点赞，点击「收藏」按钮可以把视频加入收藏夹方便以后观看。", "type": "guide"},
    {"title": "如何发送弹幕", "content": "在视频播放页面，下方有弹幕输入框。输入你想说的话，点击发送即可。你的弹幕会出现在视频画面上方。", "type": "guide"},
    {"title": "如何评论视频", "content": "在视频播放页面下方，有评论区。输入你的评论内容并提交即可与大家互动交流。", "type": "guide"},
    {"title": "如何关注 UP 主", "content": "在视频详情页或用户主页，点击「关注」按钮即可关注你喜欢的 UP 主，第一时间看到他们的新作品。", "type": "guide"},
    {"title": "支持哪些支付方式", "content": "ViewHub 目前支持平台虚拟硬币系统，你可以通过每日登录、投稿视频等方式获得硬币，用于支持喜欢的创作者。", "type": "faq"},
    {"title": "视频上传有什么限制", "content": "单个视频大小上限由系统设置决定，支持常见视频格式（MP4、MOV、AVI 等）。上传后系统会自动转码为适合在网页播放的格式。", "type": "faq"},
    {"title": "怎么查看播放历史", "content": "登录后点击头像进入个人中心，选择「播放历史」即可查看你之前看过的所有视频。", "type": "guide"},
    {"title": "如何修改个人信息", "content": "登录后进入个人中心，点击「编辑资料」可以修改头像、昵称、个人简介等信息。", "type": "guide"},
    {"title": "搜索功能怎么用", "content": "在页面顶部的搜索框输入关键词，可以搜索视频名称或 UP 主。搜索结果支持筛选和排序。", "type": "guide"},
    {"title": "AI 助手能做什么", "content": "ViewHub AI 助手可以回答关于视频内容的问题、推荐你感兴趣的视频、查询你的个人数据（播放历史、点赞收藏等），以及解答平台使用问题。", "type": "faq"},
    {"title": "如何查看视频的播放数据", "content": "在 ViewHub 视频详情页可以直接看到该视频的播放量、点赞数、投币数、收藏数、弹幕数和评论数。这些数据都是 ViewHub 平台自身的统计数据，与 bilibili、YouTube 等其他视频平台完全无关。如果你是视频作者（UP主），可以进入个人中心的发布管理查看自己视频的详细数据。", "type": "guide"},
    {"title": "视频互动数据有哪些", "content": "ViewHub 视频页展示的互动数据包括：播放量（被观看的次数）、点赞数、投币数、收藏数、弹幕数、评论数。所有数据均由 ViewHub 平台统计，来源与任何其他视频平台无关。", "type": "faq"},
    {"title": "如何联系客服", "content": "目前支持通过系统消息功能联系平台管理员。你也可以在评论区或弹幕中与其他用户互动交流。", "type": "faq"},
    {"title": "忘记密码怎么办", "content": "在登录页面点击「忘记密码」，通过注册邮箱可以重置密码。新密码设置成功后即可使用新密码登录。", "type": "guide"},
    {"title": "视频审核需要多久", "content": "视频提交后会进入审核队列，一般情况下审核结果会在几分钟到几小时内通知你。审核通过后视频即可公开播放。", "type": "faq"},
    {"title": "可以删除自己发布的视频吗", "content": "可以。进入个人中心，找到你的视频列表，点击删除即可。删除后视频将无法恢复。", "type": "guide"},
]

# 向后兼容：保留原名（其他模块可能 import）
PLATFORM_FAQ = PLATFORM_FAQ_FALLBACK


def _search_faq(query: str, top_k: int = 3) -> List[Dict[str, Any]]:
    """搜索 FAQ 缓存（DB + 兜底）"""
    faq_docs = get_faq_cache()
    query_lower = query.lower()
    if _has_chinese(query_lower):
        query_bigrams = _char_bigrams(query_lower)
        scored = []
        for doc in faq_docs:
            text = (doc["title"] + " " + doc["content"]).lower()
            text_bigrams = _char_bigrams(text)
            match_count = len(query_bigrams & text_bigrams) if text_bigrams else 0
            if match_count > 0:
                score = match_count / max(len(query_bigrams), 1)
                scored.append((doc, score))
    else:
        keywords = set(query_lower.split())
        scored = []
        for doc in faq_docs:
            text = (doc["title"] + " " + doc["content"]).lower()
            match_count = sum(1 for kw in keywords if kw in text and len(kw) > 1)
            if match_count > 0:
                score = match_count / max(len(keywords), 1)
                scored.append((doc, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    return [{
        "title": doc["title"],
        "content": doc["content"],
        "type": doc["type"],
        "score": s
    } for doc, s in scored[:top_k]]


def refresh_faq_cache():
    """强制刷新 FAQ 缓存（运营改 DB 后调用）"""
    get_faq_cache(refresh=True)
