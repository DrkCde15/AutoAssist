"""Schemas do B2B (diagnóstico + criação de chaves)."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

MAX_IMAGE_B64_LEN = 15 * 1024 * 1024


class B2BDiagnosisInput(BaseModel):
    model_config = {"extra": "ignore", "str_strip_whitespace": True}

    image: Optional[str] = Field(default=None, max_length=MAX_IMAGE_B64_LEN)
    image_b64: Optional[str] = Field(default=None, max_length=MAX_IMAGE_B64_LEN)
    pergunta: Optional[str] = Field(default=None, max_length=2000)
    formato: Literal["json", "pdf"] = "json"

    @field_validator("formato", mode="before")
    @classmethod
    def _lower_formato(cls, v: Any) -> Any:
        s = str(v or "json").strip().lower()
        return s if s in ("json", "pdf") else "json"

    @field_validator("pergunta", mode="before")
    @classmethod
    def _empty_to_none(cls, v: Any) -> Any:
        s = str(v or "").strip()
        return s or None

    def resolved_image(self) -> str:
        img = (self.image or self.image_b64 or "").strip()
        return img


class B2BCreateKeyInput(BaseModel):
    model_config = {"extra": "ignore", "str_strip_whitespace": True}

    nome: str = Field(min_length=1, max_length=120)
    rate_limit_per_min: int = Field(default=30, ge=1, le=600)
    plan: str = Field(default="trial", max_length=20)


class B2BSelfServeKeyInput(BaseModel):
    model_config = {"extra": "ignore", "str_strip_whitespace": True}

    plan: str = Field(default="trial", max_length=20)
