"""
ChatTools —— 聊天历史相关数据库操作
"""
import json
from typing import List, Dict, Any
import logging
from typing import List
from app.models import ChatHistory
from app.tools.db import get_cursor

logger = logging.getLogger(__name__)


class ChatTools:
    @staticmethod
    def save_chat_history(user_id: str, question: str, answer: str,
                          session_id: str = None, image_urls: List[str] = None,
                          videos: List[Dict[str, Any]] = None,
                          reasons: List[str] = None) -> bool:
        try:
            with get_cursor(commit=True) as cursor:
                if cursor is None:
                    return False
                cursor.execute("""
                    INSERT INTO chat_history (user_id, question, answer, session_id, image_urls, videos, reasons)
                    VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
                """, (user_id, question, answer, session_id, image_urls or [],
                      json.dumps(videos or [], ensure_ascii=False),
                      json.dumps(reasons or [], ensure_ascii=False)))
            return True
        except Exception as e:
            logger.error(f"保存聊天记录失败: {e}")
            return False

    @staticmethod
    def get_chat_history(user_id: str = None, session_id: str = None,
                         limit: int = 50) -> List[ChatHistory]:
        try:
            with get_cursor() as cursor:
                if cursor is None:
                    return []
                if session_id and user_id:
                    cursor.execute("""
                        SELECT * FROM chat_history
                        WHERE user_id = %s AND session_id = %s
                        ORDER BY created_at DESC
                        LIMIT %s
                    """, (user_id, session_id, limit))
                elif session_id:
                    cursor.execute("""
                        SELECT * FROM chat_history
                        WHERE session_id = %s
                        ORDER BY created_at DESC
                        LIMIT %s
                    """, (session_id, limit))
                elif user_id:
                    cursor.execute("""
                        SELECT * FROM chat_history
                        WHERE user_id = %s
                        ORDER BY created_at DESC
                        LIMIT %s
                    """, (user_id, limit))
                else:
                    cursor.execute("""
                        SELECT * FROM chat_history
                        ORDER BY created_at DESC
                        LIMIT %s
                    """, (limit,))
                rows = cursor.fetchall()
            return [ChatHistory(**row) for row in rows]
        except Exception as e:
            logger.error(f"获取聊天记录失败: {e}")
            return []

    @staticmethod
    def get_chat_sessions(user_id: str = None, limit: int = 20) -> List[dict]:
        try:
            with get_cursor() as cursor:
                if cursor is None:
                    return []
                if user_id:
                    cursor.execute("""
                        SELECT session_id, user_id, MIN(created_at) as first_message_at,
                               COUNT(*) as message_count, MIN(question) as first_question
                        FROM chat_history
                        WHERE user_id = %s AND session_id IS NOT NULL
                        GROUP BY session_id, user_id
                        ORDER BY first_message_at DESC
                        LIMIT %s
                    """, (user_id, limit))
                else:
                    cursor.execute("""
                        SELECT session_id, user_id, MIN(created_at) as first_message_at,
                               COUNT(*) as message_count, MIN(question) as first_question
                        FROM chat_history
                        WHERE session_id IS NOT NULL
                        GROUP BY session_id, user_id
                        ORDER BY first_message_at DESC
                        LIMIT %s
                    """, (limit,))
                rows = cursor.fetchall()
            return rows
        except Exception as e:
            logger.error(f"获取会话列表失败: {e}")
            return []

    @staticmethod
    def delete_chat_session(session_id: str) -> bool:
        try:
            with get_cursor(commit=True) as cursor:
                if cursor is None:
                    return False
                cursor.execute("DELETE FROM chat_history WHERE session_id = %s", (session_id,))
                affected = cursor.rowcount
            logger.info(f"Deleted {affected} rows for session_id: {session_id}")
            return True
        except Exception as e:
            logger.error(f"删除会话失败: {e}")
            return False
