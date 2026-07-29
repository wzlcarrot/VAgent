"""
Session —— Session 抽象

一个 Session = 一次完整对话（可能跨多个 workflow）。
注意：Harness 的状态跟踪由 CheckpointManager 负责，
本类只作为 Session 元数据的轻量数据结构。
"""
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, Any, Optional


@dataclass
class Session:
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    user_id: Optional[str] = None
    workflow_type: Optional[str] = None
    current_step: str = "init"
    status: str = "active"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "workflow_type": self.workflow_type,
            "current_step": self.current_step,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
        }
