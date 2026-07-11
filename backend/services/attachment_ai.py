import base64
import io
import logging
import os
import re

from services.groq_client import GroqHTTPError, build_chat_messages, chat_completion, utility_model
from services.vision_ai import analisar_imagem

logger = logging.getLogger(__name__)

DEFAULT_PDF_TEXT_LIMITS = (6000, 3000, 1200)
PDF_TEXT_LIMITS = tuple(
    int(item)
    for item in (os.getenv("GROQ_PDF_TEXT_LIMITS") or ",".join(map(str, DEFAULT_PDF_TEXT_LIMITS))).split(",")
    if item.strip().isdigit() and int(item) > 0
) or DEFAULT_PDF_TEXT_LIMITS
PDF_TEXT_LIMIT = max(PDF_TEXT_LIMITS)


def analisar_arquivo(file_data: bytes, mime_type: str, filename: str, pergunta: str | None = None) -> str:
    if mime_type.startswith("image/"):
        encoded = base64.b64encode(file_data).decode("ascii")
        data_url = f"data:{mime_type};base64,{encoded}"
        return analisar_imagem(data_url, pergunta)

    if mime_type == "application/pdf":
        return analisar_pdf(file_data, filename, pergunta)

    return "Não consegui analisar este formato com a Groq no momento. Envie imagem, PDF ou arquivo de texto."


def analisar_pdf(file_data: bytes, filename: str, pergunta: str | None = None) -> str:
    text = extract_pdf_text(file_data)
    if not text:
        return "Não consegui extrair texto deste PDF. Tente enviar um PDF com texto selecionável ou um arquivo TXT."

    for text_limit in PDF_TEXT_LIMITS:
        prompt = build_pdf_prompt(filename, text[:text_limit], pergunta, was_truncated=len(text) > text_limit)
        try:
            return chat_completion(
                build_chat_messages("Você é o NOG, especialista automotivo do AutoAssist.", prompt, []),
                primary_model=utility_model(),
                fallback_models=(),
                temperature=0.2,
                log_context=f"Groq PDF ({text_limit} chars)",
            )
        except GroqHTTPError as exc:
            if exc.status_code == 413:
                logger.warning("PDF excedeu o limite da Groq com %s caracteres. Reduzindo trecho.", text_limit)
                continue
            if exc.status_code == 429:
                logger.warning("Limite da Groq atingido ao analisar PDF: %s", exc)
                return (
                    "Consegui receber o PDF, mas a IA atingiu o limite de uso da Groq neste momento. "
                    "Tente novamente em alguns minutos."
                )
            logger.warning("Falha da Groq ao analisar PDF: %s", exc)
            return "Não consegui analisar este PDF no momento. Tente novamente em instantes."
        except Exception as exc:
            logger.warning("Falha inesperada ao analisar PDF: %s", exc)
            return "Não consegui analisar este PDF no momento. Tente novamente em instantes."

    return (
        "Consegui extrair texto do PDF, mas o conteúdo ainda ficou grande demais para a Groq. "
        "Tente enviar um PDF menor ou uma página específica do documento."
    )


def extract_pdf_text(file_data: bytes) -> str:
    try:
        from pypdf import PdfReader # type: ignore
    except ImportError:
        logger.warning("pypdf não instalado; análise de PDF indisponível.")
        return ""

    try:
        reader = PdfReader(io.BytesIO(file_data))
        pages = []
        for page in reader.pages[:10]:
            page_text = page.extract_text() or ""
            if page_text.strip():
                pages.append(page_text.strip())

        return normalize_pdf_text("\n\n".join(pages))[:PDF_TEXT_LIMIT]
    except Exception as exc:
        logger.warning("Falha ao extrair texto do PDF: %s", exc)
        return ""


def normalize_pdf_text(text: str) -> str:
    normalized = re.sub(r"[ \t\r\f\v]+", " ", text or "")
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def build_pdf_prompt(filename: str, text: str, pergunta: str | None = None, was_truncated: bool = False) -> str:
    question = (pergunta or "").strip() or "Analise o PDF e destaque os pontos automotivos relevantes."
    truncated_notice = (
        "\n\nObservação: o texto foi recortado para caber no limite da API. Foque no trecho disponível."
        if was_truncated else ""
    )
    return (
        "Analise o documento anexado com foco em manutenção, compra, venda, diagnóstico, documentação, "
        "custos e riscos relacionados a veículos. "
        f"Arquivo: {filename or 'anexo.pdf'}. "
        f"Pergunta do usuário: {question}\n\n"
        f"Conteúdo extraído do PDF:\n{text}{truncated_notice}"
    )
