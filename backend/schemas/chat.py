"""Schemas do chat B2C (REST /api/chat + WS /ws/chat)."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class ChatAttachmentInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    type: Optional[str] = Field(default=None, max_length=120)
    data: str = Field(min_length=1, max_length=12 * 1024 * 1024)

    @field_validator("name")
    @classmethod
    def _no_traversal(cls, v: str) -> str:
        if ".." in v or "/" in v or "\\" in v:
            raise ValueError("Nome de arquivo inválido.")
        return v.strip()


class ChatHistoryItem(BaseModel):
    role: Literal["user", "model", "assistant"] = "user"
    content: str = Field(min_length=1, max_length=4000)


class ChatInput(BaseModel):
    """Payload aceito em POST /api/chat (campos extras ignorados p/ compat)."""

    model_config = {"extra": "ignore", "str_strip_whitespace": True}

    message: str = Field(default="", max_length=4000)
    session_id: Optional[str] = Field(default=None, max_length=50)
    guest_id: Optional[str] = Field(default=None, max_length=128)
    anonymous_id: Optional[str] = Field(default=None, max_length=80)
    vehicle_id: Optional[int] = Field(default=None, ge=1)
    lat: Optional[float] = Field(default=None, ge=-90, le=90)
    lng: Optional[float] = Field(default=None, ge=-180, le=180)
    image: Optional[str] = Field(default=None, max_length=16 * 1024 * 1024)
    attachment: Optional[ChatAttachmentInput | dict[str, Any]] = None
    client_history: list[ChatHistoryItem | dict[str, Any]] = Field(default_factory=list, max_length=8)
    ignore_global_history: bool = False

    @field_validator("session_id", mode="before")
    @classmethod
    def _norm_session(cls, v: Any) -> Any:
        if v is None:
            return None
        s = str(v).strip()[:50]
        return s or None

    @field_validator("client_history", mode="before")
    @classmethod
    def _cap_history(cls, v: Any) -> Any:
        if not isinstance(v, list):
            return []
        return v[:8]

    def has_content(self) -> bool:
        return bool((self.message or "").strip() or self.image or self.attachment)
