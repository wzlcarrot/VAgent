"""
MemoryTools —— 用户长期记忆（跨 session 偏好/事实/反馈）
"""
import logging
from typing import Any, Dict, List, Optional

from app.config import settings
from app.models import Memory
from app.tools.db import get_cursor
from app.utils.security import escape_like_pattern, sanitize_search_input

logger = logging.getLogger(__name__)


def _has_chinese(text: str) -> bool:
    return any('\u4e00' <= c <= '\u9fff' for c in text)


def _extract_keywords(query: str) -> list:
    if not query:
        return []
    if _has_chinese(query):
        return [query[:50]]
    return [w for w in query.lower().split() if len(w) > 1]


def _cosine(a, b) -> float:
    """余弦相似度（0~1）。"""
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class MemoryTools:
    @staticmethod
    def _find_similar_active(cursor, user_id: str, type: str, content: str):
        """找同类型、有效、与 content 最相似的记忆 id（冲突取代的目标）。

        - pg_trgm 可用：走 similarity()，阈值 `memory_supersede_threshold`
        - 不可用：退化为 content 精确匹配
        - 找不到：返回 None
        """
        try:
            cursor.execute("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'")
            has_trgm = cursor.fetchone() is not None
        except Exception:
            has_trgm = False

        if has_trgm:
            cursor.execute(
                """
                SELECT id, similarity(content, %s) AS sim
                FROM user_memory
                WHERE user_id = %s AND type = %s AND invalid_at IS NULL
                ORDER BY sim DESC
                LIMIT 1
                """,
                (content, user_id, type),
            )
            row = cursor.fetchone()
            if row and float(row.get("sim") or 0) >= settings.memory_supersede_threshold:
                return row["id"]
            return None

        cursor.execute(
            """
            SELECT id FROM user_memory
            WHERE user_id = %s AND type = %s AND content = %s AND invalid_at IS NULL
            LIMIT 1
            """,
            (user_id, type, content),
        )
        row = cursor.fetchone()
        return row["id"] if row else None

    @staticmethod
    def _evict_over_capacity(cursor, user_id: str) -> int:
        """活跃记忆超过上限时，按「有效分」从低到高打 invalid_at（软淘汰）。"""
        max_n = max(1, int(settings.memory_max_per_user))
        try:
            cursor.execute(
                "SELECT COUNT(*) AS c FROM user_memory WHERE user_id = %s AND invalid_at IS NULL",
                (user_id,),
            )
            row = cursor.fetchone()
            count = int((row or {}).get("c") or 0)
        except Exception:
            return 0
        if count <= max_n:
            return 0
        over = count - max_n
        cursor.execute(
            """
            UPDATE user_memory SET invalid_at = NOW()
            WHERE id IN (
                SELECT id FROM user_memory
                WHERE user_id = %s AND invalid_at IS NULL
                ORDER BY (score * POWER(2, -EXTRACT(EPOCH FROM NOW() - last_accessed_at) / 864000.0)) ASC,
                         created_at ASC
                LIMIT %s
            )
            """,
            (user_id, over),
        )
        logger.info("memory evict: user=%s evicted=%d (cap=%d)", user_id, over, max_n)
        return over

    @staticmethod
    def save_memory(user_id: str, type: str, content: str, source: str = "inferred",
                    score: float = 1.0, tags: list = None, supersede: bool = True,
                    supersede_id: int = None) -> bool:
        """写入长期记忆。

        冲突处理（借鉴 ragent）：
        - 传入 `supersede_id`（来自 LLM Judge 的 SUPERSEDE 决策）→ 直接软失效该条；
        - 否则 `supersede=True` 时用相似度找旧记忆（兜底启发式）。
        旧记忆打 `invalid_at` + `superseded_by`（**软失效，不物理删除**）。
        写入后若活跃数超上限，淘汰最旧的（软失效）。
        """
        content = (content or "").strip()
        if not user_id or not content:
            return False
        try:
            with get_cursor(commit=True) as cursor:
                if cursor is None:
                    return False
                old_id = supersede_id
                if old_id is None and supersede:
                    try:
                        old_id = MemoryTools._find_similar_active(cursor, user_id, type, content)
                    except Exception as e:
                        logger.debug(f"记忆相似查找失败（跳过取代）: {e}")
                cursor.execute(
                    """
                    INSERT INTO user_memory (user_id, type, content, source, score, tags)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (user_id, type, content, source, score, tags or []),
                )
                row = cursor.fetchone()
                new_id = row.get("id") if isinstance(row, dict) else None
                if old_id and new_id:
                    cursor.execute(
                        "UPDATE user_memory SET invalid_at = NOW(), superseded_by = %s WHERE id = %s",
                        (new_id, old_id),
                    )
                    logger.info("memory supersede: user=%s old=%s new=%s", user_id, old_id, new_id)
                try:
                    MemoryTools._evict_over_capacity(cursor, user_id)
                except Exception as e:
                    logger.debug(f"记忆容量淘汰失败（不影响写入）: {e}")
            return True
        except Exception as e:
            logger.error(f"保存记忆失败: {e}")
            return False

    @staticmethod
    def retract_memory(user_id: str, memory_id: int = None, content: str = None) -> int:
        """显式遗忘：按 id 或内容把活跃记忆软失效（借鉴 ragent 的 RETRACT）。"""
        if not user_id or (memory_id is None and not content):
            return 0
        try:
            with get_cursor(commit=True) as cursor:
                if cursor is None:
                    return 0
                if memory_id is not None:
                    cursor.execute(
                        "UPDATE user_memory SET invalid_at = NOW() "
                        "WHERE user_id = %s AND id = %s AND invalid_at IS NULL",
                        (user_id, memory_id),
                    )
                else:
                    cursor.execute(
                        "UPDATE user_memory SET invalid_at = NOW() "
                        "WHERE user_id = %s AND content = %s AND invalid_at IS NULL",
                        (user_id, content),
                    )
                return cursor.rowcount or 0
        except Exception as e:
            logger.error(f"遗忘记忆失败: {e}")
            return 0

    @staticmethod
    def _semantic_recall(cursor, user_id: str, query: str) -> Optional[Dict[int, tuple]]:
        """语义通道：query 与记忆的 embedding 余弦。

        Returns:
            None  → embedding 不可用/失败（调用方应降级到关键词）
            {}    → embedding 可用，但没有命中（无相关记忆）
            {id: (row, cosine)} → 命中
        """
        try:
            from app.tools import embed_tools

            if getattr(embed_tools, "embedding_is_fallback", False):
                return None
            cursor.execute("""
                SELECT *, (score * POWER(2, -EXTRACT(EPOCH FROM NOW() - last_accessed_at) / 864000.0)) as effective_score
                FROM user_memory
                WHERE user_id = %s AND invalid_at IS NULL
                ORDER BY effective_score DESC
                LIMIT 200
            """, (user_id,))
            cand = cursor.fetchall() or []
            if not cand:
                return {}
            texts = [query] + [c.get("content", "") for c in cand]
            vecs = embed_tools.embed(texts)
            if not vecs or len(vecs) != len(texts):
                return None
            qv = vecs[0]
            out: Dict[int, tuple] = {}
            for row, vec in zip(cand, vecs[1:], strict=False):
                cos = _cosine(qv, vec)
                if cos >= settings.memory_semantic_threshold:
                    out[row["id"]] = (row, cos)
            return out
        except Exception as e:  # noqa: BLE001
            logger.debug(f"语义召回失败（降级关键词）: {e}")
            return None

    @staticmethod
    def _keyword_recall(cursor, user_id: str, keywords: List[str], top_k: int) -> List[dict]:
        """关键词通道：pg_trgm `%`（走 GIN 索引）→ ILIKE 降级 → 无命中兜底最近。"""
        if keywords:
            try:
                cursor.execute("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'")
                has_trgm = cursor.fetchone() is not None
            except Exception:
                has_trgm = False

            if has_trgm:
                like_clauses = " OR ".join(["content %% %s"] * len(keywords))
                cursor.execute(f"""
                    SELECT *, GREATEST(
                        {", ".join(["similarity(content, %s)"] * len(keywords))}
                    ) as sim,
                    (score * POWER(2, -EXTRACT(EPOCH FROM NOW() - last_accessed_at) / 864000.0)) as effective_score
                    FROM user_memory
                    WHERE user_id = %s AND invalid_at IS NULL AND ({like_clauses})
                    ORDER BY effective_score DESC
                    LIMIT %s
                """, keywords + [user_id] + keywords + [top_k])
            else:
                like_clauses = " OR ".join(["content ILIKE %s ESCAPE '\\'"] * len(keywords))
                like_params = [f"%{k}%" for k in keywords]
                cursor.execute(f"""
                    SELECT *, (score * POWER(2, -EXTRACT(EPOCH FROM NOW() - last_accessed_at) / 864000.0)) as effective_score
                    FROM user_memory
                    WHERE user_id = %s AND invalid_at IS NULL AND ({like_clauses})
                    ORDER BY effective_score DESC
                    LIMIT %s
                """, [user_id] + like_params + [top_k])
        else:
            cursor.execute("""
                SELECT *, (score * POWER(2, -EXTRACT(EPOCH FROM NOW() - last_accessed_at) / 864000.0)) as effective_score
                FROM user_memory
                WHERE user_id = %s AND invalid_at IS NULL
                ORDER BY effective_score DESC
                LIMIT %s
            """, (user_id, top_k))

        rows = cursor.fetchall()
        if not rows and keywords and settings.memory_recall_fallback:
            cursor.execute("""
                SELECT *, (score * POWER(2, -EXTRACT(EPOCH FROM NOW() - last_accessed_at) / 864000.0)) as effective_score
                FROM user_memory
                WHERE user_id = %s AND invalid_at IS NULL
                ORDER BY effective_score DESC
                LIMIT %s
            """, (user_id, top_k))
            rows = cursor.fetchall()
            if rows:
                logger.debug("记忆词面未命中，兜底返回最近记忆 %d 条", len(rows))
        return rows

    @staticmethod
    def _merge_recall(rows: List[dict], semantic: Dict[int, tuple], top_k: int) -> List[dict]:
        """关键词 rows ∪ 语义 rows，按融合分排序。

        - additive（默认）：final = w_base×时效频次 + w_sem×余弦   （加权融合，直观）
        - multiplicative：  final = 时效频次 × (1 + weight×余弦)    （时效主导）
        """
        additive = settings.memory_fusion_mode != "multiplicative"
        by_id: Dict[int, dict] = {r["id"]: dict(r) for r in rows}
        for mid, (row, _cos) in semantic.items():
            by_id.setdefault(mid, dict(row))
        scored = []
        for mid, r in by_id.items():
            cos = semantic.get(mid, (None, 0.0))[1]
            eff = float(r.get("effective_score") or r.get("score") or 0.0)
            if additive:
                r["_final"] = settings.memory_fusion_w_base * eff + settings.memory_fusion_w_sem * cos
            else:
                r["_final"] = eff * (1.0 + settings.memory_semantic_weight * cos)
            scored.append(r)
        scored.sort(key=lambda r: r["_final"], reverse=True)
        return scored[:top_k]

    @staticmethod
    def recall_memories(user_id: str, query: str = "", top_k: int = 5) -> List[Memory]:
        """
        按相关度 + 时间衰减召回用户记忆。

        性能优化：
        - 关键词查询走 pg_trgm GIN 索引：用 similarity(content, %s) 的 `%` 运算符
          （触发 idx_user_memory_content_trgm GIN 索引），阈值 >0.1 过滤弱匹配
        - 若 similarity 函数/索引不可用（扩展未建），降级到 ILIKE 全表扫描
        - 时间衰减公式：score × 2^(-Δdays/10)，10 天半衰期
        - 召回后批量 _touch，单条 UPDATE 一次完成（消除 N+1 写）
        """
        try:
            with get_cursor() as cursor:
                if cursor is None:
                    return []
                keywords = [
                    escape_like_pattern(sanitize_search_input(k, max_length=50))
                    for k in _extract_keywords(query)
                ]
                keywords = [k for k in keywords if k]
                mode = settings.memory_recall_mode
                use_semantic = bool(query) and settings.memory_semantic_recall_enabled and mode != "lexical"

                if mode == "semantic" and use_semantic:
                    # 语义优先：embedding 不可用(None) → 降级 pg_trgm 关键词
                    semantic = MemoryTools._semantic_recall(cursor, user_id, query)
                    if semantic is None:
                        logger.info("语义召回不可用，降级关键词通道")
                        rows = MemoryTools._keyword_recall(cursor, user_id, keywords, top_k)
                    else:
                        rows = MemoryTools._merge_recall([], semantic, top_k)
                else:
                    rows = MemoryTools._keyword_recall(cursor, user_id, keywords, top_k)
                    if use_semantic:
                        semantic = MemoryTools._semantic_recall(cursor, user_id, query)
                        if semantic:
                            rows = MemoryTools._merge_recall(rows, semantic, top_k)

                memory_ids = [r["id"] for r in rows]
            if memory_ids:
                MemoryTools._touch_memories(memory_ids)
            return [Memory(
                id=r["id"], user_id=r["user_id"], type=r["type"],
                content=r["content"], source=r["source"],
                score=r["score"], tags=r.get("tags"),
                created_at=r.get("created_at"),
                last_accessed_at=r.get("last_accessed_at"),
                access_count=r.get("access_count", 0),
            ) for r in rows]
        except Exception as e:
            logger.error(f"召回记忆失败: {e}")
            return []

    @staticmethod
    def active_memory_count(user_id: str) -> int:
        try:
            with get_cursor() as cursor:
                if cursor is None:
                    return 0
                cursor.execute(
                    "SELECT COUNT(*) AS c FROM user_memory WHERE user_id = %s AND invalid_at IS NULL",
                    (user_id,),
                )
                row = cursor.fetchone()
                return int((row or {}).get("c") or 0)
        except Exception as e:
            logger.debug(f"统计活跃记忆失败: {e}")
            return 0

    @staticmethod
    def list_active_memories(user_id: str, limit: int = 20, lowest_first: bool = True) -> List[Memory]:
        """列出活跃记忆（默认按有效分升序，用于挑选合并对象）。"""
        order = "ASC" if lowest_first else "DESC"
        try:
            with get_cursor() as cursor:
                if cursor is None:
                    return []
                cursor.execute(f"""
                    SELECT *, (score * POWER(2, -EXTRACT(EPOCH FROM NOW() - last_accessed_at) / 864000.0)) as effective_score
                    FROM user_memory
                    WHERE user_id = %s AND invalid_at IS NULL
                    ORDER BY effective_score {order}, created_at {order}
                    LIMIT %s
                """, (user_id, limit))
                rows = cursor.fetchall()
            return [Memory(
                id=r["id"], user_id=r["user_id"], type=r["type"], content=r["content"],
                source=r["source"], score=r["score"], tags=r.get("tags"),
                created_at=r.get("created_at"), last_accessed_at=r.get("last_accessed_at"),
                access_count=r.get("access_count", 0),
            ) for r in rows]
        except Exception as e:
            logger.error(f"列出活跃记忆失败: {e}")
            return []

    @staticmethod
    def _apply_consolidation(user_id: str, items: List[Memory], merged: List[Dict[str, Any]]) -> bool:
        """软失效原记忆 + 写入合并结果。"""
        try:
            with get_cursor(commit=True) as cursor:
                if cursor is None:
                    return False
                ids = [m.id for m in items]
                placeholders = ",".join(["%s"] * len(ids))
                cursor.execute(
                    f"UPDATE user_memory SET invalid_at = NOW() WHERE user_id = %s AND id IN ({placeholders})",
                    (user_id, *ids),
                )
                for item in merged:
                    cursor.execute(
                        """
                        INSERT INTO user_memory (user_id, type, content, source, score, tags)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (user_id, item.get("type", "preference"), item["content"], "consolidation", 0.8, []),
                    )
            return True
        except Exception as e:
            logger.error(f"记忆合并落库失败: {e}")
            return False

    @staticmethod
    def consolidate_user_memories(user_id: str, batch_size: int = None,
                                  max_rounds: int = None) -> Dict[str, Any]:
        """反复合并低分记忆，直到「降回阈值」或「没有进展」为止（二次压缩）。

        借鉴 ragent：超容量时先尝试合并，而不是直接淘汰。
        - 合并成功 → 软失效原记忆 + 写入合并结果，再进入下一轮
        - 合并有「地板」：不相关条目 LLM 合不动（返回空/条数没减少）→ 停止
        - 循环结束仍超上限时，由 `save_memory` 的容量淘汰兜底
        """
        from app.agents.memory_consolidator import consolidate_memories

        batch = max(2, int(batch_size if batch_size is not None else settings.memory_consolidate_batch))
        rounds = max(1, int(max_rounds if max_rounds is not None else settings.memory_consolidate_max_rounds))
        target = max(2, int(settings.memory_consolidate_trigger))
        before = MemoryTools.active_memory_count(user_id)
        total = 0

        for _ in range(rounds):
            items = MemoryTools.list_active_memories(user_id, limit=batch, lowest_first=True)
            if len(items) < 2:
                break
            merged = consolidate_memories(
                [{"type": m.type, "content": m.content} for m in items]
            )
            if not merged or len(merged) >= len(items):
                break  # 没有进展 → 停止（合并有地板）
            if not MemoryTools._apply_consolidation(user_id, items, merged):
                break
            total += len(items) - len(merged)
            if MemoryTools.active_memory_count(user_id) <= target:
                break

        after = MemoryTools.active_memory_count(user_id)
        result = {"consolidated": total, "before": before, "after": after}
        if total:
            logger.info("memory consolidate: user=%s %s", user_id, result)
        return result

    @staticmethod
    def archive_invalid_memories(retention_days: int = None) -> int:
        """把软失效超过保留期的记忆搬进 `user_memory_archive` 并从主表删除。

        软失效（invalid_at）保留历史可追溯，但表会持续增长；本方法做收尾：
        归档 + 清理，主表只留活跃与近期失效的记忆。返回归档行数。
        """
        days = max(1, int(retention_days if retention_days is not None else settings.memory_archive_after_days))
        try:
            with get_cursor(commit=True) as cursor:
                if cursor is None:
                    return 0
                cursor.execute(
                    """
                    INSERT INTO user_memory_archive
                        (id, user_id, type, content, source, score, tags,
                         created_at, last_accessed_at, access_count,
                         invalid_at, superseded_by, archived_at)
                    SELECT id, user_id, type, content, source, score, tags,
                           created_at, last_accessed_at, access_count,
                           invalid_at, superseded_by, NOW()
                    FROM user_memory
                    WHERE invalid_at IS NOT NULL
                      AND invalid_at < NOW() - (%s * INTERVAL '1 day')
                    """,
                    (days,),
                )
                archived = cursor.rowcount or 0
                cursor.execute(
                    """
                    DELETE FROM user_memory
                    WHERE invalid_at IS NOT NULL
                      AND invalid_at < NOW() - (%s * INTERVAL '1 day')
                    """,
                    (days,),
                )
            if archived:
                logger.info("memory archive: archived=%d (retention=%dd)", archived, days)
            return archived
        except Exception as e:
            logger.error(f"归档记忆失败: {e}")
            return 0

    @staticmethod
    def get_negative_feedback_video_ids(user_id: str, limit: int = 50) -> List[str]:
        """召回用户标记「没用」的推荐视频 ID（下次推荐降权，不硬剔除）。

        负反馈记忆的 tags 形如 ["not_helpful", session_id, "video:<id>", ...]。
        只取 not_helpful，避免把点过「有用」的也压分。
        优先合并 Redis 热缓存（反馈刚写入、DB 短暂不可用时仍可降权）。
        """
        ids: List[str] = []
        try:
            from app.tools.context_tools import _get_redis
            r = _get_redis()
            if r is not None:
                cached = r.lrange(f"vagent:neg_videos:{user_id}", 0, max(0, limit - 1))
                for raw in cached or []:
                    vid = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
                    if vid and vid not in ids:
                        ids.append(vid)
        except Exception as e:
            logger.debug(f"负反馈 Redis 读取失败: {e}")

        try:
            with get_cursor() as cursor:
                if cursor is None:
                    return ids[:limit]
                cursor.execute("""
                    SELECT content, tags FROM user_memory
                    WHERE user_id = %s AND type = 'feedback' AND %s = ANY(tags) AND invalid_at IS NULL
                    ORDER BY created_at DESC
                    LIMIT %s
                """, (user_id, "not_helpful", limit))
                rows = cursor.fetchall()
            for r in rows:
                tags = r.get("tags") or []
                for t in tags:
                    if isinstance(t, str) and t.startswith("video:"):
                        vid = t[len("video:"):]
                        if vid and vid not in ids:
                            ids.append(vid)
            return ids[:limit]
        except Exception as e:
            logger.error(f"召回负反馈视频失败: {e}")
            return ids[:limit]

    @staticmethod
    def record_negative_feedback_videos(user_id: str, video_ids: List[str]) -> None:
        """负反馈视频写入 Redis 热缓存，供推荐即时降权。"""
        if not user_id or not video_ids:
            return
        try:
            from app.tools.context_tools import _get_redis
            r = _get_redis()
            if r is None:
                return
            key = f"vagent:neg_videos:{user_id}"
            pipe = r.pipeline()
            for vid in video_ids[:20]:
                if vid:
                    pipe.lpush(key, str(vid))
            pipe.ltrim(key, 0, 99)
            pipe.expire(key, 60 * 60 * 24 * 30)
            pipe.execute()
        except Exception as e:
            logger.debug(f"负反馈 Redis 写入失败: {e}")

    @staticmethod
    def _touch_memories(memory_ids: list) -> None:
        """批量更新 last_accessed_at 和 access_count（单条 UPDATE 处理 N 条）"""
        try:
            with get_cursor(commit=True) as cursor:
                if cursor is None or not memory_ids:
                    return
                placeholders = ",".join(["%s"] * len(memory_ids))
                cursor.execute(
                    f"UPDATE user_memory SET last_accessed_at = NOW(), access_count = access_count + 1 "
                    f"WHERE id IN ({placeholders})",
                    tuple(memory_ids),
                )
        except Exception as e:
            logger.debug(f"touch memories 失败（不影响主流程）: {e}")

    @staticmethod
    def get_user_memory_stats(user_id: str) -> Dict[str, Any]:
        try:
            with get_cursor() as cursor:
                if cursor is None:
                    return {"total": 0, "types": {}}
                cursor.execute("""
                    SELECT type, COUNT(*) as cnt, AVG(score) as avg_score
                    FROM user_memory WHERE user_id = %s AND invalid_at IS NULL
                    GROUP BY type ORDER BY cnt DESC
                """, (user_id,))
                rows = cursor.fetchall()
                cursor.execute(
                    "SELECT COUNT(*) as total FROM user_memory WHERE user_id = %s AND invalid_at IS NULL",
                    (user_id,),
                )
                total = cursor.fetchone()["total"]
            return {
                "total": total,
                "types": {r["type"]: {"count": r["cnt"], "avg_score": float(r["avg_score"])} for r in rows},
            }
        except Exception as e:
            logger.error(f"获取记忆统计失败: {e}")
            return {"total": 0, "types": {}}
