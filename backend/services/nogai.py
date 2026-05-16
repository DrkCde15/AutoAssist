# nogai.py - Módulo especializado em interações de texto automotivo usando Google Gemini (New SDK)
# backend/services/nogai.py
import logging
import os
import requests
import time
from dotenv import load_dotenv
from google import genai
from google.genai import types
import json
import re
from functools import lru_cache

load_dotenv()

logger = logging.getLogger(__name__)

HTTP_TIMEOUT = (3.05, 8)
FIPE_BASE_URL = "https://parallelum.com.br/fipe/api/v1"
FIPE_CACHE_TTL_SECONDS = max(60, int(os.getenv("FIPE_CACHE_TTL_SECONDS", "86400")))

SYSTEM_PROMPT = """
Você é o NOG, um consultor automotivo profissional e mentor didático com ampla experiência no mercado brasileiro. 
Sua missão é traduzir o "mecaniquês" para uma linguagem que qualquer pessoa, mesmo leiga, consiga entender com clareza.
Sempre use o português correto e nunca exclua/"coma" palavras e informações importantes.

- Sempre que você receber um "oi" ou "olá", responda com "Olá! Sou o NOG, seu Consultor Automotivo Inteligente. Estou aqui para ajudar com suas dúvidas sobre automóveis. Como posso ajudar hoje? 🚗✨"

Diretrizes de Personalidade & Didática:
- **Mecânico Mentor**: Você é experiente e técnico, mas explica tudo como um professor paciente para quem não entende nada de carros.
- **Tradução de Termos**: Sempre que usar um termo técnico (como "junta do cabeçote", "homocinética" ou "estequiometria"), explique brevemente o que é de forma simples ou use uma analogia.
- **Uso de Analogias**: Compare peças do carro com coisas do dia a dia (Ex: "Os freios são como os pneus de um tênis de corrida...").
- **Cético e Protetor**: Continue protegendo o usuário de gastos desnecessários ou riscos de segurança, explicando o "porquê" de forma didática.

Regras de Formatação (Obrigatório):
- Use **Negrito** para termos técnicos, peças, diagnósticos e valores.
- Use > Citações para alertas de segurança ou avisos importantes.
- Use Listas pontuadas (•) para listar sintomas ou passos de verificação.
- Use Títulos (Ex: ### 💡 Entendendo o Problema) para organizar a explicação.
- Deixe uma linha em branco entre cada parágrafo para facilitar a leitura.
- Use bastante Emojis para manter o tom amigável (🔧, 🚗, ⚠️, 💡).
- Caso o assunto não for sobre automóveis ou peças de automóveis, responda: "Desculpe, mas só posso ajudar com assuntos relacionados a automóveis."

Estrutura de Resposta Padrão:
1. 🏁 **Resumo Direto**: Uma explicação simples do que está acontecendo.
2. 📖 **Dicionário do NOG**: Se houver peças complexas, explique o que elas fazem aqui.
3. 🔧 **Passo a Passo**: O que o usuário deve fazer ou verificar, ou como falar com o mecânico.
4. 💰 **Valores e FIPE**: Estimativas de custo e referências de mercado, sempre explicando o que influencia o preço.
"""

PREMIUM_TUTORIAL_PROMPT = """
[DIRETRIZ PREMIUM EXCLUSIVA PARA ESTE USUÁRIO]:
- **VÍDEOS TUTORIAIS**: O sistema em anexo vai capturar vídeos automaticamente abaixo da sua resposta. JAMAIS diga que você "não consegue mostrar vídeos por ser uma IA de texto". Se o usuário pedir um vídeo sobre o assunto, confirme educadamente: "Claro! Aqui estão alguns vídeos que encontrei para te ajudar com isso:" e termine o aviso, prosseguindo com dicas em texto.
"""

@lru_cache(maxsize=512)
def _cached_fipe_json(url: str, cache_bucket: int):
    response = requests.get(url, timeout=HTTP_TIMEOUT)
    response.raise_for_status()
    return response.json()


def _get_fipe_json(path: str):
    cache_bucket = int(time.time() // FIPE_CACHE_TTL_SECONDS)
    url = f"{FIPE_BASE_URL}/{path.lstrip('/')}"
    return _cached_fipe_json(url, cache_bucket)


def get_fipe_value(tipo, marca_nome, modelo_nome, ano):
    """Busca o valor medio de mercado via API FIPE com cache curto."""
    tipo_norm = str(tipo or "").lower()
    if tipo_norm == "carro":
        tipo_norm = "carros"
    elif tipo_norm == "moto":
        tipo_norm = "motos"
    elif tipo_norm == "caminhao":
        tipo_norm = "caminhoes"
    if tipo_norm not in {"carros", "motos", "caminhoes"}:
        return None

    marca_query = str(marca_nome or "").strip().lower()
    modelo_query = str(modelo_nome or "").strip().lower()
    ano_query = str(ano or "").strip()
    if not marca_query or not modelo_query or not ano_query:
        return None

    try:
        marcas = _get_fipe_json(f"{tipo_norm}/marcas")
        marca_obj = next((m for m in marcas if marca_query in m["nome"].lower()), None)
        if not marca_obj:
            return None

        modelos_resp = _get_fipe_json(f"{tipo_norm}/marcas/{marca_obj['codigo']}/modelos")
        candidatos = [m for m in modelos_resp.get("modelos", []) if modelo_query in m["nome"].lower()]
        if not candidatos:
            return None

        for modelo in candidatos:
            anos_disponiveis = _get_fipe_json(
                f"{tipo_norm}/marcas/{marca_obj['codigo']}/modelos/{modelo['codigo']}/anos"
            )
            ano_obj = next((a for a in anos_disponiveis if a["nome"].startswith(ano_query)), None)
            if ano_obj:
                return _get_fipe_json(
                    f"{tipo_norm}/marcas/{marca_obj['codigo']}/modelos/{modelo['codigo']}/anos/{ano_obj['codigo']}"
                )
        return None
    except Exception as e:
        logger.error(f"Erro ao buscar FIPE: {e}")
        return None

from routes.database import get_mysql_history

# Inicializa o cliente Gemini
client = genai.Client(api_key=os.getenv("API_GEMINI"))

DEFAULT_GEMINI_TEXT_MODEL = "gemini-2.5-flash"
DEFAULT_GEMINI_FALLBACK_MODELS = ("gemini-2.0-flash", "gemini-2.0-flash-lite")


def _read_int_env(name, default, minimum=0):
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


GEMINI_QUOTA_COOLDOWN_SECONDS = _read_int_env("GEMINI_QUOTA_COOLDOWN_SECONDS", 60, minimum=5)
GEMINI_FALLBACK_ON_QUOTA = os.getenv("GEMINI_FALLBACK_ON_QUOTA", "").strip().lower() in {"1", "true", "yes", "on"}
GEMINI_QUOTA_MESSAGE = (
    "O NOG atingiu o limite de uso da API do Gemini no momento. "
    "Verifique a cota/billing do projeto no Google AI Studio ou tente novamente mais tarde."
)
_gemini_quota_blocked_until = 0.0


class GeminiQuotaError(RuntimeError):
    pass


def _parse_model_list(raw_value, default_models):
    source = raw_value if raw_value is not None else ",".join(default_models)
    models = []
    seen = set()
    for item in str(source).split(","):
        model = item.strip()
        if model and model not in seen:
            seen.add(model)
            models.append(model)
    return tuple(models)


GEMINI_TEXT_MODEL = (os.getenv("GEMINI_TEXT_MODEL") or os.getenv("GEMINI_MODEL") or DEFAULT_GEMINI_TEXT_MODEL).strip()
MODELS_TO_TRY = _parse_model_list(os.getenv("GEMINI_FALLBACK_MODELS"), DEFAULT_GEMINI_FALLBACK_MODELS)

def transformar_historico_gemini(historico_mysql):
    """Converte o histórico do MySQL para o formato do novo SDK."""
    gemini_history = []
    for msg in historico_mysql:
        role = "user" if msg["role"] == "user" else "model"
        gemini_history.append(types.Content(
            role=role,
            parts=[types.Part.from_text(text=msg["content"])]
        ))
    return gemini_history

def _model_chain(primary_model=None):
    seen = set()
    for model in (primary_model or GEMINI_TEXT_MODEL, *MODELS_TO_TRY):
        model_name = str(model or "").strip()
        if model_name and model_name not in seen:
            seen.add(model_name)
            yield model_name


def _error_text(error: Exception) -> str:
    return str(error or "")


def _error_status_code(error: Exception) -> int | None:
    status_code = getattr(error, "status_code", None) or getattr(error, "code", None)
    try:
        return int(status_code)
    except (TypeError, ValueError):
        return None


def _extract_retry_delay_seconds(error: Exception) -> int | None:
    match = re.search(r"retryDelay['\"]?\s*:\s*['\"]?(\d+)s", _error_text(error))
    if match:
        return int(match.group(1))

    match = re.search(r"retry in\s+(\d+(?:\.\d+)?)s", _error_text(error), flags=re.IGNORECASE)
    if match:
        return max(1, int(float(match.group(1))))

    return None


def _is_quota_error(error: Exception) -> bool:
    if isinstance(error, GeminiQuotaError):
        return True

    error_str = _error_text(error).lower()
    return (
        _error_status_code(error) == 429
        or "resource_exhausted" in error_str
        or "quota exceeded" in error_str
        or "rate limit" in error_str
    )


def _is_model_not_found_error(error: Exception) -> bool:
    error_str = _error_text(error).lower()
    return _error_status_code(error) == 404 or ("not_found" in error_str and "not found" in error_str)


def _is_retryable_model_error(error: Exception) -> bool:
    error_str = _error_text(error)
    return (
        _error_status_code(error) in {500, 502, 503, 504}
        or "503" in error_str
        or "UNAVAILABLE" in error_str
        or "high demand" in error_str.lower()
        or "overloaded" in error_str.lower()
        or "timeout" in error_str.lower()
    )


def _should_try_fallback(error: Exception) -> bool:
    if _is_quota_error(error):
        return GEMINI_FALLBACK_ON_QUOTA

    return _is_retryable_model_error(error) or _is_model_not_found_error(error)


def _mark_quota_limited(error: Exception):
    global _gemini_quota_blocked_until

    retry_delay = _extract_retry_delay_seconds(error) or GEMINI_QUOTA_COOLDOWN_SECONDS
    _gemini_quota_blocked_until = max(_gemini_quota_blocked_until, time.time() + retry_delay)


def _raise_if_quota_cooldown_active():
    if time.time() < _gemini_quota_blocked_until:
        raise GeminiQuotaError("Gemini quota cooldown active")


def _generate_content_with_fallback(
    *,
    contents,
    config=None,
    primary_model=None,
    log_context="Gemini",
):
    _raise_if_quota_cooldown_active()
    last_error = None

    for attempt, model_name in enumerate(_model_chain(primary_model)):
        try:
            return client.models.generate_content(
                model=model_name,
                config=config,
                contents=contents,
            )
        except Exception as e:
            last_error = e
            if _is_quota_error(e):
                _mark_quota_limited(e)

            if not _should_try_fallback(e):
                if _is_quota_error(e):
                    logger.warning("%s bloqueado por quota do Gemini; fallback nao tentado.", log_context)
                raise e

            if attempt == 0:
                logger.warning("%s indisponivel em %s. Tentando modelos de fallback...", log_context, model_name)
            else:
                logger.error("Fallback para %s (%s) falhou: %s", model_name, log_context, e)

    raise last_error or RuntimeError(f"{log_context} falhou sem modelos configurados")


def _send_chat_with_fallback(*, prompt, system_instruction, history, log_context="NOG Gemini"):
    _raise_if_quota_cooldown_active()
    last_error = None

    for attempt, model_name in enumerate(_model_chain()):
        try:
            chat = client.chats.create(
                model=model_name,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.7,
                ),
                history=history,
            )
            response = chat.send_message(message=prompt)
            return response.text
        except Exception as e:
            last_error = e
            if _is_quota_error(e):
                _mark_quota_limited(e)

            if not _should_try_fallback(e):
                if _is_quota_error(e):
                    logger.warning("%s bloqueado por quota do Gemini; fallback nao tentado.", log_context)
                raise e

            if attempt == 0:
                logger.warning("%s indisponivel em %s. Tentando modelos de fallback...", log_context, model_name)
            else:
                logger.error("Fallback para %s (%s) falhou: %s", model_name, log_context, e)

    raise last_error or RuntimeError(f"{log_context} falhou sem modelos configurados")

def gerar_resposta(mensagem: str, user_id: int, user_data: dict = None, historico: list | None = None) -> str:
    try:
        logger.info(f"NOG Gemini: Processando msg do usuário {user_id}")
        
        historico_mysql = historico if historico is not None else get_mysql_history(user_id)
        historico_gemini = transformar_historico_gemini(historico_mysql)
        
        prompt_instrucoes = SYSTEM_PROMPT
        if user_data and user_data.get("is_premium"):
            prompt_instrucoes += PREMIUM_TUTORIAL_PROMPT
            
        prompt_final = mensagem
        if user_data and (user_data.get("possui_veiculo") or user_data.get("lista_veiculos")):
            veiculos = user_data.get("lista_veiculos")
            if veiculos:
                lista_str = "; ".join([f"{v.get('tipo', 'veículo')} {v.get('marca', '')} {v.get('modelo', '')} ano {v.get('ano_fabricacao', '')}".strip() for v in veiculos])
                contexto_veiculo = f"\n\n[CONTEXTO DO USUÁRIO]: O usuário possui os seguintes veículos cadastrados: {lista_str}. Responda considerando os veículos do usuário se for relevante."
            else:
                contexto_veiculo = (f"\n\n[CONTEXTO DO USUÁRIO]: O usuário possui um(a) {user_data.get('veiculo_tipo')} "
                                    f"{user_data.get('veiculo_marca')} {user_data.get('veiculo_modelo')} "
                                    f"ano {user_data.get('veiculo_ano_fabricacao')}. "
                                    f"Responda considerando este veículo se for relevante.")
            prompt_final = contexto_veiculo + "\n\nPergunta do usuário: " + mensagem
            
        return _send_chat_with_fallback(
            prompt=prompt_final,
            system_instruction=prompt_instrucoes,
            history=historico_gemini,
        )
        
    except Exception as e:
        if _is_quota_error(e):
            logger.error(f"Quota do Gemini esgotada no NOG: {e}", exc_info=True)
            return GEMINI_QUOTA_MESSAGE

        logger.error(f"❌ Erro no NOG (Gemini): {e}", exc_info=True)
        return "❌ Erro ao conectar com a inteligência na nuvem."

def _clean_search_term(value):
    if value is None:
        return None
    term = str(value).strip().replace('"', '').replace("'", "")
    if not term or term.upper() == "NONE":
        return None
    return term[:120]

def gerar_termos_busca(mensagem: str, historico: list = None) -> dict:
    """Extrai termos de busca em uma única chamada."""
    try:
        contexto_historico = ""
        if historico:
            resumo = "\n".join([f"{'Usuario' if m['role'] == 'user' else 'IA'}: {m['content']}" for m in historico[-3:]])
            contexto_historico = f"\nHistorico recente:\n{resumo}\n"

        prompt = f"""
        Extraia termos de busca a partir de conversas automotivas.
        {contexto_historico}
        Mensagem atual: "{mensagem}"
        Retorne JSON: {{"youtube": string|null, "loja": string|null, "pecas": string|null}}
        """
        response = _generate_content_with_fallback(
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json"),
            log_context="Extracao de termos",
        )
        data = json.loads(response.text)
        return {
            "youtube": _clean_search_term(data.get("youtube")),
            "loja": _clean_search_term(data.get("loja")),
            "pecas": _clean_search_term(data.get("pecas")),
        }
    except Exception:
        return {"youtube": None, "loja": None, "pecas": None}

def gerar_termo_busca_youtube(mensagem: str, historico: list = None) -> str | None:
    return gerar_termos_busca(mensagem, historico).get("youtube")

def gerar_termo_busca_loja(mensagem: str, historico: list = None) -> str | None:
    return gerar_termos_busca(mensagem, historico).get("loja")

def gerar_termo_busca_pecas(mensagem: str, historico: list = None) -> str | None:
    return gerar_termos_busca(mensagem, historico).get("pecas")

def prever_intervalo_manutencao(descricao: str, veiculo_info: str = "") -> dict:
    """Preve o intervalo de manutenção com base na descrição."""
    try:
        prompt = f"""
        Especialista automotivo: preveja o próximo retorno (dias e km).
        Descrição: "{descricao}"
        {f"Veículo: {veiculo_info}" if veiculo_info else ""}
        Retorne JSON: {{"intervalo_dias": int|null, "intervalo_km": int|null, "justificativa": str}}
        """
        response = _generate_content_with_fallback(
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json"),
            log_context="Previsao manutencao",
        )
        return json.loads(response.text)
    except Exception:
        return {"intervalo_dias": None, "intervalo_km": None, "justificativa": "Falha na análise"}
