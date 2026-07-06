import base64
import logging

from dotenv import load_dotenv

from services.groq_client import chat_completion, vision_fallback_models, vision_model

load_dotenv()

logger = logging.getLogger(__name__)

VISION_PROMPT = """
Você é o NOG, especialista em inspeção veicular técnica ("Raio-X Mecânico").
Analise a imagem buscando falhas ocultas e detalhes de mercado.

Sua resposta deve conter:
1. 📋 Resumo do estado: lataria, pneus, pintura, interior e detalhes visíveis.
2. 🔧 Alerta mecânico: possíveis problemas comuns para esse tipo/modelo de veículo.
3. 💰 Estimativa de valor: veredito prático, como Bom estado, Cuidado ou Alto risco.

Tratamento de imagens não relacionadas a automóveis:
- Caso a imagem não seja sobre automóveis ou peças automotivas, responda:
  "Desculpe, mas só posso ajudar com imagens relacionadas a automóveis."

Seja didático, use negrito para termos técnicos e proteja o comprador.
"""


def analisar_imagem(image_b64: str, pergunta: str | None = None) -> str:
    try:
        logger.info("Groq Vision: analisando imagem.")
        data_url = _normalize_image_data_url(image_b64)

        return chat_completion(
            build_vision_messages(data_url, pergunta),
            primary_model=vision_model(),
            fallback_models=vision_fallback_models(),
            temperature=0.2,
            log_context="Groq Vision",
        )
    except Exception as exc:
        logger.error("Erro na análise de visão Groq: %s", exc, exc_info=True)
        return "❌ O NOG não conseguiu analisar esta imagem no momento."


def build_vision_messages(data_url: str, pergunta: str | None = None) -> list[dict]:
    prompt = f"{VISION_PROMPT.strip()}\n\n{_build_image_prompt(pergunta)}"
    return [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        }
    ]


def _build_image_prompt(pergunta: str | None = None) -> str:
    question = (pergunta or "").strip()
    if not question:
        return "A imagem está anexada no item image_url. Analise a imagem diretamente com foco automotivo."
    return (
        "A imagem está anexada no item image_url. Analise a imagem diretamente. "
        f"Pergunta específica do usuário: {question}"
    )


def _normalize_image_data_url(image_b64: str) -> str:
    value = str(image_b64 or "").strip()
    if value.startswith("data:image/"):
        try:
            _validate_base64(value.split(",", 1)[1] if "," in value else "")
            return value
        except Exception:
            pass # Fallback para re-encapsulamento se o prefixo estiver malformado

    encoded = value.split(",", 1)[1] if "," in value else value
    try:
        _validate_base64(encoded)
        return f"data:image/jpeg;base64,{encoded}"
    except Exception as e:
        logger.error("Base64 inválido fornecido para visão.")
        raise ValueError("Dados de imagem inválidos.") from e


def _validate_base64(encoded: str):
    base64.b64decode(encoded, validate=True)
