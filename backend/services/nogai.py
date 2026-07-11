# nogai.py - Módulo especializado em interações de texto automotivo usando Groq
# backend/services/nogai.py
import logging
import os
import requests
import time
from dotenv import load_dotenv
import json
import re
from functools import lru_cache
from types import SimpleNamespace
from utils.cache import TTLCache
from services.web_scraping import WebScraper

load_dotenv()

logger = logging.getLogger(__name__)

HTTP_TIMEOUT = (3.05, 8)
FIPE_BASE_URL = "https://parallelum.com.br/fipe/api/v1"
FIPE_CACHE_TTL_SECONDS = max(60, int(os.getenv("FIPE_CACHE_TTL_SECONDS", "86400")))
_fipe_result_cache = TTLCache(default_ttl=FIPE_CACHE_TTL_SECONDS, maxsize=1024)

_ai_response_cache = {}  # user_id -> TTLCache
_AI_CACHE_TTL = int(os.getenv("AI_CACHE_TTL_SECONDS", "300"))


def _get_ai_cache(user_id):
    cache = _ai_response_cache.get(user_id)
    if cache is None:
        cache = TTLCache(default_ttl=_AI_CACHE_TTL, maxsize=256)
        _ai_response_cache[user_id] = cache
    return cache


def _invalidate_user_ai_cache(user_id):
    """Invalida todas as respostas em cache de um usuário (ex.: após editar manutenção)."""
    _ai_response_cache.pop(user_id, None)

_SIMPLE_GREETINGS = re.compile(
    r"^(oi|ol[áa]|bom dia|boa tarde|boa noite|e a[ií]|hello|hey|opa|iae|blz|be?leza|tudo bem|como vai)$",
    re.IGNORECASE,
)

GREETING_PROMPT = """
Você é o NOG, consultor automotivo amigável e acolhedor. Quando o usuário enviar uma saudação simples ("oi", "olá", "bom dia", "boa tarde", "boa noite", "e aí", "tudo bem" etc), responda com calor humano e entusiasmo, como se estivesse recebendo um amigo.
Sempre que você receber um "oi" ou "olá", responda com 
DIRETRIZES:
- Responda em NO MÁXIMO 2 linhas, mas com um tom caloroso e convidativo.
- Use emojis relacionados a carros ou ferramentas 🚗🔧⚡ (apenas 1 por resposta).
- NÃO use formatação markdown (**negrito**, ###, listas, citações).
- NÃO use seções, dicionário nem passos.
- Se houver veículo cadastrado, algo como: "Olá! Sou o NOG, seu Consultor Automotivo Inteligente. Estou aqui para ajudar com suas dúvidas sobre automóveis. Vi que você tem um [veículo], como posso ajudar hoje? 🚗✨"
- Se NÃO houver veículo cadastrado, algo como: Olá! Sou o NOG, seu Consultor Automotivo Inteligente. Estou aqui para ajudar com suas dúvidas sobre automóveis, como posso ajudar hoje? 🚗✨"
- NÃO peça para cadastrar veículo — apenas pergunte como pode ajudar.
- Seja breve, mas transmita simpatia e disposição para ajudar.
"""

SYSTEM_PROMPT = """
Você é o NOG, consultor automotivo e mentor didático para o mercado brasileiro.
Traduza "mecaniquês" para leigos usando analogias do dia a dia.
Seja cético e protetor: evite gastos desnecessários e explique riscos.

Formatação: use **negrito** para termos técnicos, > citação para alertas, ### Título para seções, • para listas.
Para saudações ("oi", "olá"), use a mensagem de boas-vindas padrão.
Se o assunto não for automotivo, responda: "Desculpe, mas só posso ajudar com assuntos relacionados a automóveis."

Precisão:
- [CONTEXTO AUTOASSIST] é a fonte principal para dados do usuário.
- Diferencie fatos de previsões ML. Não invente dados não cadastrados.

Estrutura da resposta:
1. Resumo Direto: explicação simples do problema.
2. Dicionário do NOG: termos técnicos explicados.
3. Passo a Passo: o que fazer ou como falar com o mecânico.
4. Valores e FIPE: estimativas de custo e referências de mercado.
"""

PREMIUM_TUTORIAL_PROMPT = """
[DIRETRIZ PREMIUM EXCLUSIVA PARA ESTE USUÁRIO]:
- **VÍDEOS TUTORIAIS**: O sistema em anexo vai capturar vídeos automaticamente abaixo da sua resposta. JAMAIS diga que você 
"não consegue mostrar vídeos por ser uma IA de texto". Se o usuário pedir um vídeo sobre o assunto, confirme educadamente: 
"Claro! Aqui estão alguns vídeos que encontrei para te ajudar com isso:" e termine o aviso, prosseguindo com dicas em texto.
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


def _extract_fipe_year(value):
    if isinstance(value, dict):
        text = f"{value.get('nome', '')} {value.get('codigo', '')}"
    else:
        text = str(value or "")

    match = re.search(r"\b(19\d{2}|20\d{2}|21\d{2})\b", text)
    if not match:
        return None
    return int(match.group(1))


def _enrich_fipe_result(result, match_type, requested_year, used_year=None, used_model=None):
    if not isinstance(result, dict):
        return result

    enriched = dict(result)
    enriched["fipe_match_type"] = match_type
    if requested_year:
        enriched["AnoConsultado"] = str(requested_year)
    if used_year is not None:
        enriched["AnoFipeUsado"] = str(used_year)
    if used_model:
        enriched["ModeloFipeUsado"] = used_model
    return enriched


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
    requested_year = _extract_fipe_year(ano)
    ano_query = str(requested_year or ano or "").strip()
    if not marca_query or not modelo_query or not ano_query:
        return None

    fipe_key = (tipo_norm, marca_query, modelo_query, ano_query)
    cached = _fipe_result_cache.get(fipe_key)
    if cached is not None:
        return cached

    try:
        marcas = _get_fipe_json(f"{tipo_norm}/marcas")
        marca_obj = next((m for m in marcas if marca_query in m["nome"].lower()), None)
        if not marca_obj:
            return None

        modelos_resp = _get_fipe_json(f"{tipo_norm}/marcas/{marca_obj['codigo']}/modelos")
        candidatos = [m for m in modelos_resp.get("modelos", []) if modelo_query in m["nome"].lower()]

        # Fallback 1: tentar com apenas a primeira palavra do modelo
        if not candidatos:
            first_word = modelo_query.split()[0] if " " in modelo_query else None
            if first_word:
                candidatos = [m for m in modelos_resp.get("modelos", []) if first_word in m["nome"].lower()]

        # Fallback 2: remover sufixos comuns (v8, v6, 4x4, tb, cd, etc.)
        if not candidatos:
            simpler = re.sub(r"\b(v8|v6|v4|4x4|4x2|tb|cd|aut|mec|flex|die|gas|ht)\b", "", modelo_query).strip()
            if simpler and simpler != modelo_query:
                candidatos = [m for m in modelos_resp.get("modelos", []) if simpler in m["nome"].lower()]

        if not candidatos:
            return None

        nearest_year_match = None
        for modelo in candidatos:
            anos_disponiveis = _get_fipe_json(
                f"{tipo_norm}/marcas/{marca_obj['codigo']}/modelos/{modelo['codigo']}/anos"
            )
            ano_obj = next((a for a in anos_disponiveis if a["nome"].startswith(ano_query)), None)
            if ano_obj:
                result = _get_fipe_json(
                    f"{tipo_norm}/marcas/{marca_obj['codigo']}/modelos/{modelo['codigo']}/anos/{ano_obj['codigo']}"
                )
                result = _enrich_fipe_result(
                    result,
                    match_type="exact",
                    requested_year=ano_query,
                    used_year=_extract_fipe_year(ano_obj),
                    used_model=modelo["nome"],
                )
                _fipe_result_cache.set(fipe_key, result)
                return result

            if requested_year is None:
                continue

            for available_year in anos_disponiveis:
                year_number = _extract_fipe_year(available_year)
                if year_number is None:
                    continue

                # In a tie, prefer an older year to avoid overestimating market value.
                sort_key = (
                    abs(year_number - requested_year),
                    1 if year_number > requested_year else 0,
                )
                if nearest_year_match is None or sort_key < nearest_year_match["sort_key"]:
                    nearest_year_match = {
                        "sort_key": sort_key,
                        "modelo": modelo,
                        "ano": available_year,
                        "year_number": year_number,
                    }

        if nearest_year_match:
            modelo = nearest_year_match["modelo"]
            ano_obj = nearest_year_match["ano"]
            result = _get_fipe_json(
                f"{tipo_norm}/marcas/{marca_obj['codigo']}/modelos/{modelo['codigo']}/anos/{ano_obj['codigo']}"
            )
            enriched = _enrich_fipe_result(
                result,
                match_type="nearest_year",
                requested_year=ano_query,
                used_year=nearest_year_match["year_number"],
                used_model=modelo["nome"],
            )
            if isinstance(enriched, dict):
                enriched["fipe_warning"] = (
                    f"FIPE exata para {ano_query} nao encontrada; "
                    f"usado ano {nearest_year_match['year_number']}."
                )
            _fipe_result_cache.set(fipe_key, enriched)
            return enriched
        result = None
        _fipe_result_cache.set(fipe_key, result)
        return result
    except Exception as e:
        logger.error(f"Erro ao buscar FIPE: {e}")
        return None

from services.groq_client import build_chat_messages, chat_completion, utility_model, utility_fallback_models

DEFAULT_TEXT_MODEL = "groq/compound-mini"
DEFAULT_FALLBACK_MODELS = ("groq/compound",)


def _read_int_env(name, default, minimum=0):
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


GROQ_QUOTA_COOLDOWN_SECONDS = _read_int_env("GROQ_QUOTA_COOLDOWN_SECONDS", 120, minimum=5)
TRUE_ENV_VALUES = {"1", "true", "yes", "on"}
FALSE_ENV_VALUES = {"0", "false", "no", "off"}


def _read_bool_env(name, default=False):
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    normalized_value = raw_value.strip().lower()
    if normalized_value in TRUE_ENV_VALUES:
        return True
    if normalized_value in FALSE_ENV_VALUES:
        return False
    return default


GROQ_FALLBACK_ON_QUOTA = _read_bool_env("GROQ_FALLBACK_ON_QUOTA", default=True)
GROQ_QUOTA_MESSAGE = (
    "O NOG atingiu o limite de sua API no momento. Tente novamente em alguns minutos. Agradecemos sua compreensão!"
)
GROQ_TEMPORARY_UNAVAILABLE_MESSAGE = (
    "O NOG está com alta demanda no momento. Tente novamente em alguns minutos."
)
_groq_quota_blocked_until_by_model = {}


class GroqQuotaError(RuntimeError):
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


GROQ_PRIMARY_MODEL = (os.getenv("GROQ_PRIMARY_MODEL") or os.getenv("GROQ_MODEL") or DEFAULT_TEXT_MODEL).strip()
MODELS_TO_TRY = _parse_model_list(os.getenv("GROQ_FALLBACK_MODELS"), DEFAULT_FALLBACK_MODELS)

def _cache_key(mensagem: str, historico: list | None, user_id=None) -> str:
    history_tail = json.dumps(historico[-2:] if historico else [], ensure_ascii=False)
    return f"{user_id}|{mensagem[:200]}|{hash(history_tail)}"

def _get_cached(key: str, user_id=None):
    cache = _ai_response_cache.get(user_id)
    if cache is None:
        return None
    return cache.get(key)

def _set_cache(key: str, response: str, user_id=None):
    _get_ai_cache(user_id).set(key, response)

def _is_simple_query(mensagem: str) -> bool:
    return bool(_SIMPLE_GREETINGS.match(mensagem.strip()))


_AUTOMOTIVE_TERMS = (
    "carro", "veiculo", "veiculo", "automovel", "moto", "motocicleta",
    "caminhao", "caminhonete", "onibus", "frota",
    "motor", "motorista", "km", "quilometragem", "quilometro",
    "manutencao", "revisao", "oleo", "lubrificante",
    "filtro", "pneu", "pneus", "freio", "freios", "pastilha", "disco",
    "bateria", "correia", "arrefecimento", "radiador", "suspensao",
    "amortecedor", "troca", "fipe", "multa", "licenciamento", "documento",
    "mecanico", "oficina", "peca", "pecas", "vistoria",
    "airbag", "embreagem", "cambio", "gasolina", "etanol",
    "diesel", "abastecer", "tanque", "recall", "garantia", "seguro",
    "automativo", "automovel",
)


def _is_automotive_query(mensagem: str) -> bool:
    """Verifica se a mensagem tem relacao com assuntos automotivos."""
    import unicodedata
    normalized = unicodedata.normalize("NFKD", (mensagem or "").lower())
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return any(term in normalized for term in _AUTOMOTIVE_TERMS)

def transformar_historico(historico_mysql):
    """Converte o histórico do MySQL para o formato OpenAI-compatible, truncando para economizar tokens."""
    groq_history = []
    for msg in historico_mysql:
        role = "user" if msg["role"] == "user" else "assistant"
        content = str(msg.get("content") or "").strip()[:1200]
        if content:
            groq_history.append({"role": role, "content": content})
    return groq_history

def _model_chain(primary_model=None):
    seen = set()
    for model in (primary_model or GROQ_PRIMARY_MODEL, *MODELS_TO_TRY):
        model_name = str(model or "").strip()
        if model_name and model_name not in seen:
            seen.add(model_name)
            yield model_name


def _error_text(error: Exception) -> str:
    return str(error or "")


def _error_summary(error: Exception, max_length=240) -> str:
    summary = re.sub(r"\s+", " ", _error_text(error)).strip()
    if len(summary) <= max_length:
        return summary
    return f"{summary[:max_length - 3]}..."


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
    if isinstance(error, GroqQuotaError):
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
        return GROQ_FALLBACK_ON_QUOTA

    return _is_retryable_model_error(error) or _is_model_not_found_error(error)


def _mark_model_quota_limited(model_name: str, error: Exception):
    retry_delay = _extract_retry_delay_seconds(error) or GROQ_QUOTA_COOLDOWN_SECONDS
    blocked_until = time.time() + retry_delay
    current_blocked_until = _groq_quota_blocked_until_by_model.get(model_name, 0.0)
    _groq_quota_blocked_until_by_model[model_name] = max(current_blocked_until, blocked_until)
    return retry_delay


def _is_model_quota_limited(model_name: str) -> bool:
    blocked_until = _groq_quota_blocked_until_by_model.get(model_name, 0.0)
    if time.time() < blocked_until:
        return True

    _groq_quota_blocked_until_by_model.pop(model_name, None)
    return False


def _models_available_for_request(primary_model=None):
    models = tuple(_model_chain(primary_model))
    available_models = tuple(model_name for model_name in models if not _is_model_quota_limited(model_name))
    if models and not available_models:
        raise GroqQuotaError("All Groq models are in quota cooldown")
    return available_models


def _generate_content_with_fallback(
    *,
    contents,
    config=None,
    primary_model=None,
    fallback_models=None,
    log_context="Groq",
    response_format=None,
    temperature=None,
):
    text = chat_completion(
        build_chat_messages("", contents, []),
        primary_model=primary_model,
        fallback_models=fallback_models,
        response_format=response_format,
        temperature=temperature,
        log_context=log_context,
    )
    return SimpleNamespace(text=text)


def _send_chat_with_fallback(*, prompt, system_instruction, history, primary_model=None, log_context="NOG Groq"):
    return chat_completion(
        build_chat_messages(system_instruction, prompt, history),
        primary_model=primary_model,
        log_context=log_context,
    )

_maintenance_ctx_cache = TTLCache(default_ttl=180, maxsize=1024)


def _invalidate_maintenance_context(user_id):
    """Invalida o contexto de manutenção em cache de um usuário (após editar manutenções)."""
    _maintenance_ctx_cache.delete(user_id)


def _build_maintenance_context(user_id):
    """Monta um resumo textual do histórico de manutenções do usuário para o contexto da IA."""
    try:
        from datetime import date
        from routes.database import get_db
        from services.maintenance_service import _status_from_remaining

        cached = _maintenance_ctx_cache.get(user_id)
        if cached is not None:
            return cached

        with get_db() as (cur, conn):
            cur.execute(
                """SELECT mh.maintenance_label, mh.maintenance_type,
                          mh.service_date, mh.service_km, mh.cost, mh.currency,
                          mh.next_due_date,
                          v.marca, v.modelo
                   FROM maintenance_history mh
                   LEFT JOIN veiculos v ON v.id = mh.vehicle_id
                   WHERE mh.user_id = %s
                   ORDER BY mh.service_date DESC, mh.created_at DESC
                   LIMIT 15""",
                (user_id,),
            )
            rows = cur.fetchall()

        if not rows:
            return ""

        lines = []
        for r in rows:
            label = r.get("maintenance_label") or r.get("maintenance_type") or "Manutencao"
            svc = r.get("service_date")
            svc_str = svc.strftime("%d/%m/%Y") if hasattr(svc, "strftime") else str(svc or "")
            due = r.get("next_due_date")
            due_str = due.strftime("%d/%m/%Y") if hasattr(due, "strftime") else (str(due) if due else None)
            km = r.get("service_km")
            veh = f"{r.get('marca') or ''} {r.get('modelo') or ''}".strip()

            days_remaining = None
            if due is not None:
                try:
                    due_d = due.date() if hasattr(due, "date") else due
                    days_remaining = (due_d - date.today()).days
                except Exception:
                    days_remaining = None
            status_label, _ = _status_from_remaining(days_remaining, None)

            partes = [f"- {label}"]
            if veh:
                partes.append(f"({veh})")
            partes.append(f"em {svc_str}")
            if km is not None:
                partes.append(f"a {km} km")
            if due_str:
                partes.append(f"-> prox. em {due_str} [{status_label}]")
            lines.append(" ".join(partes))

        context = "\n".join(lines)
        _maintenance_ctx_cache.set(user_id, context)
        return context
    except Exception as e:
        logger.warning("Falha ao montar contexto de manutencao: %s", e)
        return ""


def gerar_resposta(mensagem: str, user_id: int, user_data: dict = None, historico: list | None = None) -> str:
    try:
        logger.info(f"NOG Groq: Processando msg do usuário {user_id}")

        if not mensagem or not mensagem.strip():
            return "Por favor, digite uma mensagem para eu poder ajudar. 🚗"

        msg_clean = mensagem.strip()

        if historico is None:
            from routes.database import get_mysql_history
            historico_mysql = get_mysql_history(user_id)
        else:
            historico_mysql = historico
        historico_groq = transformar_historico(historico_mysql)

        cache_key = _cache_key(msg_clean, historico_groq, user_id)
        cached = _get_cached(cache_key, user_id)
        if cached:
            logger.info(f"Cache hit para usuário {user_id}")
            return cached

        use_utility = _is_simple_query(msg_clean)

        if use_utility:
            prompt_instrucoes = GREETING_PROMPT
        else:
            prompt_instrucoes = SYSTEM_PROMPT
            if user_data and user_data.get("is_premium"):
                prompt_instrucoes += PREMIUM_TUTORIAL_PROMPT

        user_context = ""
        veiculos = user_data.get("lista_veiculos") if user_data else None

        if veiculos:
            lista_str = "; ".join([f"{v.get('tipo', 'veículo')} {v.get('marca', '')} {v.get('modelo', '')} ano {v.get('ano_fabricacao', '')}".strip() for v in veiculos])
            user_context = f"\n\n[CONTEXTO DO USUÁRIO]: O usuário possui os seguintes veículos cadastrados: {lista_str}."
        elif user_data and user_data.get("possui_veiculo"):
            user_context = (f"\n\n[CONTEXTO DO USUÁRIO]: O usuário possui um(a) {user_data.get('veiculo_tipo')} "
                            f"{user_data.get('veiculo_marca')} {user_data.get('veiculo_modelo')} "
                            f"ano {user_data.get('veiculo_ano_fabricacao')}.")

        autoassist_context = (user_data or {}).get("chat_context")
        if autoassist_context:
            user_context += f"\n\n[CONTEXTO AUTOASSIST]\n{autoassist_context}"

        manut_context = _build_maintenance_context(user_id) if _is_automotive_query(msg_clean) else ""
        if manut_context:
            user_context += (
                f"\n\n[CONTEXTO DE MANUTENCAO]: Historico de manutencoes do usuario "
                f"(mais recentes):\n{manut_context}"
            )

        prompt_final = f"{user_context}\n\nPergunta do usuário: {msg_clean}" if user_context else msg_clean

        if use_utility:
            response = _send_chat_with_fallback(
                prompt=prompt_final,
                system_instruction=prompt_instrucoes,
                history=historico_groq,
                primary_model=utility_model(),
                log_context="NOG (util)",
            )
        else:
            response = _send_chat_with_fallback(
                prompt=prompt_final,
                system_instruction=prompt_instrucoes,
                history=historico_groq,
            )

        _set_cache(cache_key, response, user_id)
        return response

    except Exception as e:
        if _is_quota_error(e):
            logger.warning("Quota da Groq esgotada no NOG: %s", _error_summary(e))
            return GROQ_QUOTA_MESSAGE

        if _is_retryable_model_error(e):
            logger.warning("Groq temporariamente indisponivel no NOG: %s", _error_summary(e))
            return GROQ_TEMPORARY_UNAVAILABLE_MESSAGE

        logger.error(f"❌ Erro no NOG (Groq): {e}", exc_info=True)
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
            resumo = "\n".join([
                f"{'Usuario' if m.get('role') == 'user' else 'IA'}: {str(m.get('content') or '')[:500]}"
                for m in historico[-2:]
                if isinstance(m, dict)
            ])
            contexto_historico = f"\nHistorico recente:\n{resumo}\n"

        mensagem_curta = str(mensagem or "")[:900]
        prompt = f"""
        Extraia termos de busca a partir de conversas automotivas.
        {contexto_historico}
        Mensagem atual: "{mensagem_curta}"
        Retorne JSON: {{"youtube": string|null, "loja": string|null, "pecas": string|null}}
        """
        response = _generate_content_with_fallback(
            contents=prompt,
            primary_model=utility_model(),
            fallback_models=utility_fallback_models(),
            response_format={"type": "json_object"},
            temperature=0.2,
            log_context="Extracao de termos",
        )
        try:
            data = json.loads(response.text)
        except json.JSONDecodeError:
            return {"youtube": None, "loja": None, "pecas": None}
        return {
            "youtube": _clean_search_term(data.get("youtube")),
            "loja": _clean_search_term(data.get("loja")),
            "pecas": _clean_search_term(data.get("pecas")),
        }
    except Exception:
        return {"youtube": None, "loja": None, "pecas": None}

def gerar_termo_busca_youtube(mensagem: str, historico: list = None) -> str | None:
    return gerar_termos_busca(mensagem, historico).get("youtube")

def gerar_termo_busca_loja(mensagem: str, historico: list = None) -> list[dict]:
    """Extrai termo de busca e retorna links para lojas de veículos."""
    termo = gerar_termos_busca(mensagem, historico).get("loja")
    if not termo:
        return []
    try:
        scraper = WebScraper()
        links = scraper.search_car_stores(termo)
        for link in links:
            link.setdefault("tipo", "veiculo")
            link.setdefault("icon", "fas fa-car")
        return links
    except Exception as e:
        logger.error(f"Erro ao gerar links de loja: {e}")
        return []

def gerar_termo_busca_pecas(mensagem: str, historico: list = None) -> list[dict]:
    """Extrai termo de busca e retorna links para compra de peças."""
    termo = gerar_termos_busca(mensagem, historico).get("pecas")
    if not termo:
        return []
    try:
        scraper = WebScraper()
        links = scraper.search_car_parts(termo)
        for link in links:
            link.setdefault("tipo", "peca")
            link.setdefault("icon", "fas fa-tools")
        return links
    except Exception as e:
        logger.error(f"Erro ao gerar links de peças: {e}")
        return []

_prever_cache = TTLCache(default_ttl=3600, maxsize=512)

def prever_intervalo_manutencao(descricao: str, veiculo_info: str = "") -> dict:
    """Preve o intervalo de manutenção com base na descrição."""
    key = (descricao, veiculo_info)
    cached = _prever_cache.get(key)
    if cached is not None:
        return cached
    try:
        prompt = f"""
        Especialista automotivo: preveja o próximo retorno (dias e km).
        Descrição: "{descricao}"
        {f"Veículo: {veiculo_info}" if veiculo_info else ""}
        Retorne JSON: {{"intervalo_dias": int|null, "intervalo_km": int|null, "justificativa": str}}
        """
        response = _generate_content_with_fallback(
            contents=prompt,
            primary_model=utility_model(),
            fallback_models=utility_fallback_models(),
            response_format={"type": "json_object"},
            temperature=0.2,
            log_context="Previsao manutencao",
        )
        try:
            result = json.loads(response.text)
        except json.JSONDecodeError:
            result = {"intervalo_dias": None, "intervalo_km": None, "justificativa": "Erro ao processar resposta da IA"}
    except Exception:
        result = {"intervalo_dias": None, "intervalo_km": None, "justificativa": "Falha na análise"}
    _prever_cache.set(key, result)
    return result
