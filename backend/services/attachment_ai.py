import base64
import logging

from google.genai import types

from services.vision_ai import analisar_imagem, client

logger = logging.getLogger(__name__)

FILE_MODELS_TO_TRY = ("gemini-2.5-flash", "gemini-2.0-flash", "gemini-flash-latest")


def analisar_arquivo(file_data: bytes, mime_type: str, filename: str, pergunta: str | None = None) -> str:
    if mime_type.startswith("image/"):
        encoded = base64.b64encode(file_data).decode("ascii")
        data_url = f"data:{mime_type};base64,{encoded}"
        return analisar_imagem(data_url, pergunta)

    prompt = build_file_prompt(filename, mime_type, pergunta)
    file_part = types.Part.from_bytes(data=file_data, mime_type=mime_type)

    for model in FILE_MODELS_TO_TRY:
        try:
            response = client.models.generate_content(model=model, contents=[prompt, file_part])
            if response.text:
                return response.text
        except Exception as exc:
            logger.warning("Falha ao analisar anexo %s com %s: %s", filename, model, exc)

    return "Não consegui analisar este arquivo no momento. Tente novamente ou envie outro formato suportado."


def build_file_prompt(filename: str, mime_type: str, pergunta: str | None = None) -> str:
    question = (pergunta or "").strip() or "Analise o arquivo anexado e destaque os pontos automotivos relevantes."
    return (
        "Você é o NOG, especialista automotivo do AutoAssist. "
        "Analise o arquivo anexado com foco em manutenção, compra, venda, diagnóstico, documentação, "
        "custos e riscos relacionados a veículos. "
        f"Arquivo: {filename or 'anexo'} ({mime_type}). "
        f"Pergunta do usuário: {question}"
    )
