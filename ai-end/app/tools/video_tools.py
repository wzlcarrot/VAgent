"""
VideoTools —— 视频元数据相关数据库操作
"""
import logging
from typing import List, Optional
from app.models import VideoInfo
from app.tools.db import get_cursor

logger = logging.getLogger(__name__)


_VIDEO_SELECT_SQL = """
    SELECT v.video_id, v.video_cover, v.video_name, v.user_id,
           v.create_time, v.last_update_time, v.p_category_id, v.category_id,
           v.post_type, v.origin_info, v.tags, v.introduction, v.interaction,
           v.duration, v.play_count, v.like_count, v.danmu_count, v.comment_count,
           v.coin_count, v.collect_count, v.recommend_type, v.last_play_time,
           u.nick_name
    FROM video_info v
    LEFT JOIN user_info u ON v.user_id = u.user_id
"""


def _row_to_video_info(row: dict) -> VideoInfo:
    return VideoInfo(
        videoId=row.get("video_id"),
        videoCover=row.get("video_cover"),
        videoName=row.get("video_name"),
        userId=row.get("user_id"),
        createTime=row.get("create_time"),
        lastUpdateTime=row.get("last_update_time"),
        pCategoryId=row.get("p_category_id"),
        categoryId=row.get("category_id"),
        postType=row.get("post_type"),
        originInfo=row.get("origin_info"),
        tags=row.get("tags"),
        introduction=row.get("introduction"),
        interaction=row.get("interaction"),
        duration=row.get("duration"),
        playCount=row.get("play_count"),
        likeCount=row.get("like_count"),
        danmuCount=row.get("danmu_count"),
        commentCount=row.get("comment_count"),
        coinCount=row.get("coin_count"),
        collectCount=row.get("collect_count"),
        recommendType=row.get("recommend_type"),
        lastPlayTime=row.get("last_play_time"),
        nickName=row.get("nick_name"),
    )


class VideoTools:
    @staticmethod
    def get_video_info(video_id: str) -> Optional[VideoInfo]:
        try:
            with get_cursor() as cursor:
                if cursor is None:
                    return None
                cursor.execute(
                    _VIDEO_SELECT_SQL + " WHERE v.video_id = %s",
                    (video_id,),
                )
                row = cursor.fetchone()
            return _row_to_video_info(row) if row else None
        except Exception as e:
            logger.error(f"获取视频信息失败: {e}")
            return None

    @staticmethod
    def get_video_info_batch(video_ids: List[str]) -> List[VideoInfo]:
        if not video_ids:
            return []
        try:
            with get_cursor() as cursor:
                if cursor is None:
                    return []
                placeholders = ",".join(["%s"] * len(video_ids))
                cursor.execute(
                    _VIDEO_SELECT_SQL + f" WHERE v.video_id IN ({placeholders})",
                    tuple(video_ids),
                )
                rows = cursor.fetchall()
            return [_row_to_video_info(row) for row in rows]
        except Exception as e:
            logger.error(f"批量获取视频信息失败: {e}")
            return []

    @staticmethod
    def get_recent_videos(limit: int = 10) -> List[VideoInfo]:
        try:
            with get_cursor() as cursor:
                if cursor is None:
                    return []
                cursor.execute(
                    _VIDEO_SELECT_SQL + " ORDER BY v.create_time DESC LIMIT %s",
                    (limit,),
                )
                rows = cursor.fetchall()
            return [_row_to_video_info(row) for row in rows]
        except Exception as e:
            logger.error(f"获取最新视频失败: {e}")
            return []
