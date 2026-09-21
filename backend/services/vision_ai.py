import base64
import logging
import os

from dotenv import load_dotenv

from services.groq_client import chat_completion, vision_fallback_models, vision_model
from utils.cache import cache_get_json, cache_set_json, make_cache_key

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

Regras de formatação (obrigatórias):
- Comece a resposta DIRETAMENTE com a análise. Não inclua preâmbulos, não
  reescreva a pergunta do usuário e não faça comentários sobre o que ele quer
  ou sobre a imagem de forma introdutória.
- Não exiba seu raciocínio interno, nem etapas de pensamento, nem texto entre
  colchetes, chaves ou tags como <think>/<thinking>. Vá direto ao conteúdo.
"""


def analisar_imagem(image_b64: str, pergunta: str | None = None, reference_images=None) -> str:
    try:
        data_url = _normalize_image_data_url(image_b64)
        reference_images = [r for r in (reference_images or []) if r]

        # Diagnóstico visual assistido: a comparação depende da foto de
        # referência, então não faz sentido cachear por apenas a imagem atual.
        cached = None
        if not reference_images:
            cache_key = make_cache_key("groq:vision", image_b64, pergunta or "", vision_model())
            cached = cache_get_json(cache_key)
            if cached is not None:
                return cached

        result = chat_completion(
            build_vision_messages(data_url, pergunta, reference_images),
            primary_model=vision_model(),
            fallback_models=vision_fallback_models(),
            temperature=0.2,
            log_context="Groq Vision",
        )
        if not reference_images:
            cache_set_json(
                cache_key,
                result,
                ttl=int(os.getenv("GROQ_VISION_CACHE_TTL_SECONDS", "86400")),
            )
        return result
    except Exception as exc:
        logger.error("Erro na análise de visão Groq: %s", exc, exc_info=True)
        return "❌ O NOG não conseguiu analisar esta imagem no momento."


def build_vision_messages(data_url: str, pergunta: str | None = None, reference_images=None) -> list[dict]:
    reference_images = [r for r in (reference_images or []) if r]
    content = [{"type": "text", "text": _build_image_prompt(pergunta)}]
    if reference_images:
        content.append({"type": "text", "text": _build_reference_prompt(len(reference_images))})
    content.append({"type": "image_url", "image_url": {"url": data_url}})
    for ref in reference_images:
        content.append({"type": "image_url", "image_url": {"url": ref}})
    return [
        {
            "role": "system",
            "content": VISION_PROMPT.strip(),
        },
        {
            "role": "user",
            "content": content,
        },
    ]


def _build_image_prompt(pergunta: str | None = None) -> str:
    question = (pergunta or "").strip()
    if not question:
        return "A imagem está anexada no item image_url. Analise a imagem diretamente com foco automotivo."
    return (
        "A imagem está anexada no item image_url. Analise a imagem diretamente. "
        f"Pergunta específica do usuário: {question}"
    )


def _build_reference_prompt(qtd: int) -> str:
    return (
        f"A(s) próxima(s) {qtd} imagem(ns) pertence(m) ao MESMO veículo, registrada(s) "
        "anteriormente pelo proprietário (memória visual do veículo). Compare com a imagem "
        "principal enviada agora: aponte o que é novo, o que piorou, o que melhorou ou se está "
        "de acordo com o estado anterior. Use essa comparação para enriquecer o veredito e a "
        "estimativa de valor, sem inventar dados que não estejam nas imagens."
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
