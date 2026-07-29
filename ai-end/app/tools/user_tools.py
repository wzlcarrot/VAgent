"""
UserTools —— 用户数据相关数据库操作
"""
import logging
from typing import List, Dict, Any, Optional
from app.models import VideoPlayHistory
from app.tools.db import get_cursor

logger = logging.getLogger(__name__)


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
                    "AND DATE(action_time) = CURRENT_DATE",
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
                    "AND action_time >= date_trunc('week', CURRENT_DATE)::date",
                    (user_id,),
                )
                row = cursor.fetchone()
            return row[0] if row else 0
        except Exception as e:
            logger.error(f"获取本周点赞数失败: {e}")
            return 0

    @staticmethod
    def get_today_favorite_count(user_id: str) -> int:
        try:
            with get_cursor(cursor_factory=None) as cursor:
                if cursor is None:
                    return 0
                cursor.execute(
                    "SELECT COUNT(*) FROM user_action WHERE user_id = %s AND action_type = 3 "
                    "AND DATE(action_time) = CURRENT_DATE",
                    (user_id,),
                )
                row = cursor.fetchone()
            return row[0] if row else 0
        except Exception as e:
            logger.error(f"获取今日收藏数失败: {e}")
            return 0

    @staticmethod
    def get_recent_liked_videos(user_id: str, limit: int = 10) -> Dict[str, Any]:
        try:
            with get_cursor() as cursor:
                if cursor is None:
                    return {"videos": [], "total": 0}
                cursor.execute(
                    "SELECT video_id, video_name FROM user_action "
                    "WHERE user_id = %s AND action_type = 2 "
                    "ORDER BY action_time DESC LIMIT %s",
                    (user_id, limit),
                )
                rows = cursor.fetchall()
                cursor.execute(
                    "SELECT COUNT(*) FROM user_action WHERE user_id = %s AND action_type = 2",
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
    def get_recent_favorites(user_id: str, limit: int = 10) -> Dict[str, Any]:
        try:
            with get_cursor() as cursor:
                if cursor is None:
                    return {"videos": [], "total": 0}
                cursor.execute(
                    "SELECT video_id, video_name FROM user_action "
                    "WHERE user_id = %s AND action_type = 3 "
                    "ORDER BY action_time DESC LIMIT %s",
                    (user_id, limit),
                )
                rows = cursor.fetchall()
                cursor.execute(
                    "SELECT COUNT(*) FROM user_action WHERE user_id = %s AND action_type = 3",
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
    def get_recent_history(user_id: str, limit: int = 10) -> Dict[str, Any]:
        try:
            with get_cursor() as cursor:
                if cursor is None:
                    return {"videos": [], "total": 0}
                cursor.execute(
                    "SELECT video_id, last_update_time FROM video_play_history "
                    "WHERE user_id = %s "
                    "ORDER BY last_update_time DESC LIMIT %s",
                    (user_id, limit),
                )
                rows = cursor.fetchall()
                cursor.execute(
                    "SELECT COUNT(*) FROM video_play_history WHERE user_id = %s",
                    (user_id,),
                )
                total = cursor.fetchone()
            return {
                "videos": [{"video_id": r["video_id"], "video_name": ""} for r in rows],
                "total": total["count"] if total else 0,
            }
        except Exception as e:
            logger.error(f"获取播放历史失败: {e}")
            return {"videos": [], "total": 0}

    @staticmethod
    def get_top_liked_videos(user_id: str, limit: int = 3) -> List[Dict[str, Any]]:
        try:
            with get_cursor() as cursor:
                if cursor is None:
                    return []
                cursor.execute(
                    "SELECT video_id, video_name, COUNT(*) as cnt FROM user_action "
                    "WHERE user_id = %s AND action_type = 2 "
                    "GROUP BY video_id, video_name ORDER BY cnt DESC LIMIT %s",
                    (user_id, limit),
                )
                rows = cursor.fetchall()
            return [{"video_id": r["video_id"], "video_name": r["video_name"], "count": r["cnt"]} for r in rows]
        except Exception as e:
            logger.error(f"获取点赞最多视频失败: {e}")
            return []
