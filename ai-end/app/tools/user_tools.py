"""
UserTools —— 用户数据相关数据库操作
"""
import logging
from typing import Any, Dict, List, Optional

from app.models import VideoPlayHistory
from app.tools.db import get_cursor

logger = logging.getLogger(__name__)

# 会话 TimeZone=Asia/Shanghai。用半开区间代替 DATE(col)，索引更好走。
# timestamptz 会转到上海日历；timestamp without tz 按会话时区解读（与主站 JVM 本地时一致）。
def _sql_on_today(col: str) -> str:
    return (
        f"{col} >= date_trunc('day', CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Shanghai') "
        f"AND {col} < date_trunc('day', CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Shanghai') "
        f"+ INTERVAL '1 day'"
    )


def _sql_on_week(col: str) -> str:
    return (
        f"{col} >= date_trunc('week', CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Shanghai') "
        f"AND {col} < date_trunc('week', CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Shanghai') "
        f"+ INTERVAL '7 days'"
    )


class UserTools:
    @staticmethod
    def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
        try:
            with get_cursor() as cursor:
                if cursor is None:
                    return None
                cursor.execute(
                    "SELECT user_id, email, password, nick_name, avatar FROM user_info WHERE email = %s",
                    (email,),
                )
                row = cursor.fetchone()
            return row
        except Exception as e:
            logger.error(f"通过邮箱获取用户失败: {e}")
            return None

    @staticmethod
    def update_user_password(user_id: str, password_hash: str) -> bool:
        """更新用户密码哈希（用于旧 MD5 → bcrypt 透明升级）"""
        try:
            with get_cursor(commit=True) as cursor:
                if cursor is None:
                    return False
                cursor.execute(
                    "UPDATE user_info SET password = %s WHERE user_id = %s",
                    (password_hash, user_id),
                )
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"更新用户密码失败: {e}")
            return False

    @staticmethod
    def get_play_history(user_id: str, limit: int = 50) -> List[VideoPlayHistory]:
        try:
            with get_cursor() as cursor:
                if cursor is None:
                    return []
                cursor.execute(
                    "SELECT user_id, video_id, file_index, last_update_time "
                    "FROM video_play_history WHERE user_id = %s ORDER BY last_update_time DESC LIMIT %s",
                    (user_id, limit),
                )
                rows = cursor.fetchall()
            return [VideoPlayHistory(**row) for row in rows]
        except Exception as e:
            logger.error(f"获取播放历史失败: {e}")
            return []

    @staticmethod
    def get_favorites(user_id: str, limit: int = 50) -> List[str]:
        try:
            with get_cursor() as cursor:
                if cursor is None:
                    return []
                cursor.execute(
                    "SELECT video_id FROM user_action WHERE user_id = %s AND action_type = 3 "
                    "ORDER BY action_time DESC LIMIT %s",
                    (user_id, limit),
                )
                rows = cursor.fetchall()
            return [row["video_id"] for row in rows]
        except Exception as e:
            logger.error(f"获取收藏列表失败: {e}")
            return []

    @staticmethod
    def get_liked_videos(user_id: str, limit: int = 50) -> List[str]:
        try:
            with get_cursor() as cursor:
                if cursor is None:
                    return []
                cursor.execute(
                    "SELECT video_id FROM user_action WHERE user_id = %s AND action_type = 2 "
                    "ORDER BY action_time DESC LIMIT %s",
                    (user_id, limit),
                )
                rows = cursor.fetchall()
            return [row["video_id"] for row in rows]
        except Exception as e:
            logger.error(f"获取点赞列表失败: {e}")
            return []

    @staticmethod
    def get_total_like_count(user_id: str) -> int:
        try:
            with get_cursor(cursor_factory=None) as cursor:
                if cursor is None:
                    return 0
                cursor.execute(
                    "SELECT COUNT(*) FROM user_action WHERE user_id = %s AND action_type = 2",
                    (user_id,),
                )
                row = cursor.fetchone()
            return row[0] if row else 0
        except Exception as e:
            logger.error(f"获取点赞总数失败: {e}")
            return 0

    @staticmethod
    def get_total_favorite_count(user_id: str) -> int:
        try:
            with get_cursor(cursor_factory=None) as cursor:
                if cursor is None:
                    return 0
                cursor.execute(
                    "SELECT COUNT(*) FROM user_action WHERE user_id = %s AND action_type = 3",
                    (user_id,),
                )
                row = cursor.fetchone()
            return row[0] if row else 0
        except Exception as e:
            logger.error(f"获取收藏总数失败: {e}")
            return 0

    @staticmethod
    def get_today_like_count(user_id: str) -> int:
        try:
            with get_cursor(cursor_factory=None) as cursor:
                if cursor is None:
                    return 0
                cursor.execute(
                    "SELECT COUNT(*) FROM user_action WHERE user_id = %s AND action_type = 2 "
                    f"AND {_sql_on_today('action_time')}",
                    (user_id,),
                )
                row = cursor.fetchone()
            return row[0] if row else 0
        except Exception as e:
            logger.error(f"获取今日点赞数失败: {e}")
            return 0

    @staticmethod
    def get_week_like_count(user_id: str) -> int:
        try:
            with get_cursor(cursor_factory=None) as cursor:
                if cursor is None:
                    return 0
                cursor.execute(
                    "SELECT COUNT(*) FROM user_action WHERE user_id = %s AND action_type = 2 "
                    f"AND {_sql_on_week('action_time')}",
                    (user_id,),
                )
                row = cursor.fetchone()
            return row[0] if row else 0
        except Exception as e:
            logger.error(f"获取本周点赞数失败: {e}")
            return 0

    @staticmethod
    def get_week_favorite_count(user_id: str) -> int:
        try:
            with get_cursor(cursor_factory=None) as cursor:
                if cursor is None:
                    return 0
                cursor.execute(
                    "SELECT COUNT(*) FROM user_action WHERE user_id = %s AND action_type = 3 "
                    f"AND {_sql_on_week('action_time')}",
                    (user_id,),
                )
                row = cursor.fetchone()
            return row[0] if row else 0
        except Exception as e:
            logger.error(f"获取本周收藏数失败: {e}")
            return 0

    @staticmethod
    def get_today_favorite_count(user_id: str) -> int:
        try:
            with get_cursor(cursor_factory=None) as cursor:
                if cursor is None:
                    return 0
                cursor.execute(
                    "SELECT COUNT(*) FROM user_action WHERE user_id = %s AND action_type = 3 "
                    f"AND {_sql_on_today('action_time')}",
                    (user_id,),
                )
                row = cursor.fetchone()
            return row[0] if row else 0
        except Exception as e:
            logger.error(f"获取今日收藏数失败: {e}")
            return 0

    @staticmethod
    def get_recent_liked_videos(user_id: str, limit: int = 10, time_range: str = "all") -> Dict[str, Any]:
        try:
            with get_cursor() as cursor:
                if cursor is None:
                    return {"videos": [], "total": 0}
                time_sql = ""
                if time_range == "today":
                    time_sql = f" AND {_sql_on_today('ua.action_time')}"
                elif time_range == "week":
                    time_sql = f" AND {_sql_on_week('ua.action_time')}"
                cursor.execute(
                    "SELECT ua.video_id, vi.video_name FROM user_action ua "
                    "LEFT JOIN video_info vi ON ua.video_id = vi.video_id "
                    "WHERE ua.user_id = %s AND ua.action_type = 2" + time_sql + " "
                    "ORDER BY ua.action_time DESC LIMIT %s",
                    (user_id, limit),
                )
                rows = cursor.fetchall()
                cursor.execute(
                    "SELECT COUNT(*) FROM user_action ua WHERE ua.user_id = %s AND ua.action_type = 2" + time_sql,
                    (user_id,),
                )
                total = cursor.fetchone()
            return {
                "videos": [{"video_id": r["video_id"], "video_name": r["video_name"]} for r in rows],
                "total": total["count"] if total else 0,
            }
        except Exception as e:
            logger.error(f"获取最近点赞视频失败: {e}")
            return {"videos": [], "total": 0}

    @staticmethod
    def get_recent_favorites(user_id: str, limit: int = 10, time_range: str = "all") -> Dict[str, Any]:
        try:
            with get_cursor() as cursor:
                if cursor is None:
                    return {"videos": [], "total": 0}
                time_sql = ""
                if time_range == "today":
                    time_sql = f" AND {_sql_on_today('ua.action_time')}"
                elif time_range == "week":
                    time_sql = f" AND {_sql_on_week('ua.action_time')}"
                cursor.execute(
                    "SELECT ua.video_id, vi.video_name FROM user_action ua "
                    "LEFT JOIN video_info vi ON ua.video_id = vi.video_id "
                    "WHERE ua.user_id = %s AND ua.action_type = 3" + time_sql + " "
                    "ORDER BY ua.action_time DESC LIMIT %s",
                    (user_id, limit),
                )
                rows = cursor.fetchall()
                cursor.execute(
                    "SELECT COUNT(*) FROM user_action ua WHERE ua.user_id = %s AND ua.action_type = 3" + time_sql,
                    (user_id,),
                )
                total = cursor.fetchone()
            return {
                "videos": [{"video_id": r["video_id"], "video_name": r["video_name"]} for r in rows],
                "total": total["count"] if total else 0,
            }
        except Exception as e:
            logger.error(f"获取最近收藏视频失败: {e}")
            return {"videos": [], "total": 0}

    @staticmethod
    def get_recent_history(user_id: str, limit: int = 10, time_range: str = "all") -> Dict[str, Any]:
        try:
            with get_cursor() as cursor:
                if cursor is None:
                    return {"videos": [], "total": 0}
                time_sql = ""
                if time_range == "today":
                    time_sql = f" AND {_sql_on_today('ph.last_update_time')}"
                elif time_range == "week":
                    time_sql = f" AND {_sql_on_week('ph.last_update_time')}"
                cursor.execute(
                    "SELECT ph.video_id, vi.video_name FROM video_play_history ph "
                    "LEFT JOIN video_info vi ON ph.video_id = vi.video_id "
                    "WHERE ph.user_id = %s" + time_sql + " "
                    "ORDER BY ph.last_update_time DESC LIMIT %s",
                    (user_id, limit),
                )
                rows = cursor.fetchall()
                count_sql = "SELECT COUNT(*) FROM video_play_history ph WHERE ph.user_id = %s" + time_sql
                cursor.execute(count_sql, (user_id,))
                total = cursor.fetchone()
            return {
                "videos": [{"video_id": r["video_id"], "video_name": r["video_name"] or ""} for r in rows],
                "total": total["count"] if total else 0,
            }
        except Exception as e:
            logger.error(f"获取播放历史失败: {e}")
            return {"videos": [], "total": 0}

    @staticmethod
    def get_coin_count(user_id: str) -> int:
        """当前硬币余额（user_info.current_coin_count）。"""
        try:
            with get_cursor(cursor_factory=None) as cursor:
                if cursor is None:
                    return 0
                cursor.execute(
                    "SELECT current_coin_count FROM user_info WHERE user_id = %s",
                    (user_id,),
                )
                row = cursor.fetchone()
            return int(row[0]) if row and row[0] is not None else 0
        except Exception as e:
            logger.error(f"获取硬币余额失败: {e}")
            return 0

    @staticmethod
    def get_followings(user_id: str, limit: int = 10) -> Dict[str, Any]:
        """我关注的 up 主列表（user_focus + user_info）。"""
        try:
            with get_cursor() as cursor:
                if cursor is None:
                    return {"users": [], "total": 0}
                cursor.execute(
                    "SELECT uf.focus_user_id, ui.nick_name FROM user_focus uf "
                    "LEFT JOIN user_info ui ON uf.focus_user_id = ui.user_id "
                    "WHERE uf.user_id = %s ORDER BY uf.focus_time DESC LIMIT %s",
                    (user_id, limit),
                )
                rows = cursor.fetchall()
                cursor.execute(
                    "SELECT COUNT(*) FROM user_focus WHERE user_id = %s",
                    (user_id,),
                )
                total = cursor.fetchone()
            users = [
                {
                    "user_id": r["focus_user_id"],
                    "nick_name": r["nick_name"] or "未知用户",
                }
                for r in rows
            ]
            return {
                "users": users,
                "total": total["count"] if total else 0,
            }
        except Exception as e:
            logger.error(f"获取关注列表失败: {e}")
            return {"users": [], "total": 0}

    @staticmethod
    def get_top_liked_videos(user_id: str, limit: int = 3) -> List[Dict[str, Any]]:
        try:
            with get_cursor() as cursor:
                if cursor is None:
                    return []
                cursor.execute(
                    "SELECT ua.video_id, vi.video_name, COUNT(*) as cnt FROM user_action ua "
                    "LEFT JOIN video_info vi ON ua.video_id = vi.video_id "
                    "WHERE ua.user_id = %s AND ua.action_type = 2 "
                    "GROUP BY ua.video_id, vi.video_name ORDER BY cnt DESC LIMIT %s",
                    (user_id, limit),
                )
                rows = cursor.fetchall()
            return [{"video_id": r["video_id"], "video_name": r["video_name"], "count": r["cnt"]} for r in rows]
        except Exception as e:
            logger.error(f"获取点赞最多视频失败: {e}")
            return []
