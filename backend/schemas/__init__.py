"""Schemas Pydantic v2 para validação de entradas (chat B2C + B2B).

Uso:
    from schemas import ChatInput, B2BDiagnosisInput, B2BCreateKeyInput
    payload = ChatInput.model_validate(request.get_json(silent=True) or {})
"""
from .chat import ChatAttachmentInput, ChatInput
from .b2b import B2BDiagnosisInput, B2BCreateKeyInput, B2BSelfServeKeyInput

__all__ = [
    "ChatAttachmentInput",
    "ChatInput",
    "B2BDiagnosisInput",
    "B2BCreateKeyInput",
    "B2BSelfServeKeyInput",
]
