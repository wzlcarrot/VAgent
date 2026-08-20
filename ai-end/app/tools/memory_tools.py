"""
MemoryTools —— 用户长期记忆（跨 session 偏好/事实/反馈）
"""
import logging
from typing import Any, Dict, List

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


class MemoryTools:
    @staticmethod
    def save_memory(user_id: str, type: str, content: str, source: str = "inferred",
                    score: float = 1.0, tags: list = None) -> bool:
        try:
            with get_cursor(commit=True) as cursor:
                if cursor is None:
                    return False
                cursor.execute(
                    """
                    INSERT INTO user_memory (user_id, type, content, source, score, tags)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (user_id, type, content, source, score, tags or []),
                )
            return True
        except Exception as e:
            logger.error(f"保存记忆失败: {e}")
            return False

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
                            WHERE user_id = %s AND ({like_clauses})
                            ORDER BY effective_score DESC
                            LIMIT %s
                        """, keywords + [user_id] + keywords + [top_k])
                    else:
                        like_clauses = " OR ".join(
                            ["content ILIKE %s ESCAPE '\\'"] * len(keywords)
                        )
                        like_params = [f"%{k}%" for k in keywords]
                        cursor.execute(f"""
                            SELECT *, (score * POWER(2, -EXTRACT(EPOCH FROM NOW() - last_accessed_at) / 864000.0)) as effective_score
                            FROM user_memory
                            WHERE user_id = %s AND ({like_clauses})
                            ORDER BY effective_score DESC
                            LIMIT %s
                        """, [user_id] + like_params + [top_k])
                else:
                    cursor.execute("""
                        SELECT *, (score * POWER(2, -EXTRACT(EPOCH FROM NOW() - last_accessed_at) / 864000.0)) as effective_score
                        FROM user_memory
                        WHERE user_id = %s
                        ORDER BY effective_score DESC
                        LIMIT %s
                    """, (user_id, top_k))

                rows = cursor.fetchall()
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
    def get_negative_feedback_video_ids(user_id: str, limit: int = 50) -> List[str]:
        """召回用户标记"没用"的推荐视频 ID（用于下次推荐降权/剔除）。

        负反馈记忆的 tags 形如 ["not_helpful", session_id, "video:<id>", ...]。
        只取 not_helpful，避免把点过「有用」的视频也剔除。
        """
        try:
            with get_cursor() as cursor:
                if cursor is None:
                    return []
                cursor.execute("""
                    SELECT content, tags FROM user_memory
                    WHERE user_id = %s AND type = 'feedback' AND %s = ANY(tags)
                    ORDER BY created_at DESC
                    LIMIT %s
                """, (user_id, "not_helpful", limit))
                rows = cursor.fetchall()
            ids = []
            for r in rows:
                tags = r.get("tags") or []
                for t in tags:
                    if isinstance(t, str) and t.startswith("video:"):
                        vid = t[len("video:"):]
                        if vid and vid not in ids:
                            ids.append(vid)
            return ids
        except Exception as e:
            logger.error(f"召回负反馈视频失败: {e}")
            return []

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
                    FROM user_memory WHERE user_id = %s
                    GROUP BY type ORDER BY cnt DESC
                """, (user_id,))
                rows = cursor.fetchall()
                cursor.execute(
                    "SELECT COUNT(*) as total FROM user_memory WHERE user_id = %s",
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
