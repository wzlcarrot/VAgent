from pydantic import BaseModel, Field, field_validator
from typing import Optional, List
from datetime import datetime
from app.config import settings


class VideoInfo(BaseModel):
    videoId: Optional[str] = None
    videoCover: Optional[str] = None
    videoName: Optional[str] = None
    userId: Optional[str] = None
    createTime: Optional[datetime] = None
    lastUpdateTime: Optional[datetime] = None
    pCategoryId: Optional[int] = None
    categoryId: Optional[int] = None
    postType: Optional[int] = None
    originInfo: Optional[str] = None
    tags: Optional[str] = None
    introduction: Optional[str] = None
    interaction: Optional[str] = None
    duration: Optional[int] = None
    playCount: Optional[int] = None
    likeCount: Optional[int] = None
    danmuCount: Optional[int] = None
    commentCount: Optional[int] = None
    coinCount: Optional[int] = None
    collectCount: Optional[int] = None
    recommendType: Optional[int] = None
    lastPlayTime: Optional[datetime] = None
    nickName: Optional[str] = None
    avatar: Optional[str] = None

    model_config = {"from_attributes": True}


class VideoPlayHistory(BaseModel):
    userId: Optional[str] = Field(None, alias="user_id")
    videoId: Optional[str] = Field(None, alias="video_id")
    fileIndex: Optional[int] = Field(None, alias="file_index")
    lastUpdateTime: Optional[datetime] = Field(None, alias="last_update_time")
    videoCover: Optional[str] = Field(None, alias="video_cover")
    videoName: Optional[str] = Field(None, alias="video_name")

    model_config = {"populate_by_name": True}


# 单个 image_url 上限：兼容前端 base64 dataUrl（5MB 图片 → ~6.7M 字符），
# 防止绕过 nginx 8m 限制的直连超大 payload
MAX_IMAGE_URL_CHARS = 8_000_000
MAX_IMAGE_URLS_TOTAL_CHARS = 7_500_000


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=settings.max_question_length)
    userId: Optional[str] = Field(None, alias="user_id")
    videoId: Optional[str] = Field(None, alias="video_id")
    sessionId: Optional[str] = Field(None, alias="session_id")
    imageUrls: Optional[List[str]] = Field(
        default=None, alias="image_urls", max_length=settings.max_image_urls
    )

    model_config = {"populate_by_name": True}

    @field_validator("imageUrls")
    @classmethod
    def validate_image_urls(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if not v:
            return v
        total_chars = 0
        for url in v:
            if not isinstance(url, str):
                raise ValueError("image_url 必须是字符串")
            if len(url) > MAX_IMAGE_URL_CHARS:
                raise ValueError(f"image_url 过长（单条超过 {MAX_IMAGE_URL_CHARS} 字符）")
            total_chars += len(url)
        if total_chars > MAX_IMAGE_URLS_TOTAL_CHARS:
            raise ValueError("image_urls 总大小超限")
        return v


class ChatHistory(BaseModel):
    id: Optional[int] = None
    user_id: Optional[str] = None
    question: Optional[str] = None
    answer: Optional[str] = None
    session_id: Optional[str] = None
    image_urls: Optional[List[str]] = None
    videos: Optional[List[dict]] = None
    reasons: Optional[List[str]] = None
    created_at: Optional[datetime] = None

    model_config = {"populate_by_name": True}


class Memory(BaseModel):
    id: Optional[int] = None
    user_id: str
    type: str = "preference"
    content: str
    source: str = "inferred"
    score: float = 1.0
    tags: Optional[List[str]] = None
    created_at: Optional[datetime] = None
    last_accessed_at: Optional[datetime] = None
    access_count: int = 0

    model_config = {"from_attributes": True}


class LoginRequest(BaseModel):
    email: str
    password: str


class AuthResponse(BaseModel):
    user: dict