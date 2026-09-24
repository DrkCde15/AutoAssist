"""Rotas web principais (Blueprint ``pages``) — fachada fina (P1).

Os 112 handlers (40 rotas) moram em ``routes/pages_split/*.py`` e são
carregados abaixo compartilhando este namespace (imports, ``pages_bp``,
constantes, ``logger``). Isso evita import circular entre os splits, que
têm referências cruzadas (ex.: ``pages_chat`` usa
``pages_vehicles.get_vehicle_reference_images`` e vice-versa).

Compatibilidade preservada::

    from routes.pages import pages_bp, chat, parse_chat_attachment

Roadmap: evoluir para blueprints reais (``chat_bp``, ``vehicles_bp``…)
com imports explícitos + lazy imports nos pontos de ciclo, e então
eliminar o ``exec``. Até lá, este loader é a cola — ver
``_load_split_modules()``.
"""
import base64
import hashlib
import html
import io
import json
import logging
import mimetypes
import os
import re
import threading
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from functools import lru_cache
from time import monotonic

from flask import (
    Blueprint,
    current_app,
    jsonify,
    request,
    send_file,
    send_from_directory,
)
from flask_jwt_extended import get_jwt_identity, jwt_required, verify_jwt_in_request
from pydub import AudioSegment
import speech_recognition as sr

from extensions import limiter
from services.maintenance_service import (
    _status_from_remaining,
    apply_manual_overrides,
    parse_maintenance_entry,
    serialize_maintenance_row,
)
from services.nogai import (
    _invalidate_maintenance_context,
    _invalidate_user_ai_cache,
    prever_intervalo_manutencao,
)
from services.web_scraping import WebScraper
from utils.async_task import _predictor
from utils.email import enviar_email
from utils.turnstile import turnstile_or_auth

from .analytics import has_prior_event, record_analytics_event
from .database import (
    get_db,
    get_mysql_history,
    get_trial_days_remaining,
    is_trial_expired,
)
from .notifications import create_notification
from .push import send_push_notification

pages_bp = Blueprint('pages', __name__)
logger = logging.getLogger(__name__)

PREMIUM_ONLY_ERROR = "Recurso exclusivo para Premium"
INVALID_SESSION_ERROR = "Sessao invalida. Faca login novamente."
CRITICAL_MAINTENANCE_STATUSES = ("overdue",)
ACTIONABLE_MAINTENANCE_STATUSES = ("overdue", "due_soon")
MAINTENANCE_DISPATCH_LOCK_NAME = "autoassist_maintenance_email_dispatcher"
_maintenance_dispatch_thread_lock = threading.Lock()
_maintenance_dispatch_last_started_at = 0.0

GENERIC_CHAT_TOKENS = {
    "ai",
    "bem",
    "boa",
    "bom",
    "dia",
    "e",
    "noite",
    "obrigada",
    "obrigado",
    "oi",
    "ola",
    "opa",
    "salve",
    "tarde",
    "tudo",
    "valeu",
}

GUEST_CHAT_LIMIT = 5
# P0-1: free registrado ganha quota mensal de interações no chat.
# Premium é ilimitado. Evita burn infinito de IA em contas gratuitas.
FREE_MONTHLY_CHAT_LIMIT = int(os.getenv("FREE_MONTHLY_CHAT_LIMIT", "30"))
# P1-1: free pode registrar até N manutenções; premium é ilimitado.
FREE_MAINTENANCE_LIMIT = int(os.getenv("FREE_MAINTENANCE_LIMIT", "3"))
MAX_CHAT_HISTORY_LIMIT = 200
DEFAULT_CHAT_HISTORY_LIMIT = 100
MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024
TEXT_ATTACHMENT_LIMIT = 12000
IMAGE_ATTACHMENT_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
BINARY_ATTACHMENT_TYPES = {"application/pdf"}
TEXT_ATTACHMENT_TYPES = {
    "application/json",
    "application/xml",
    "text/csv",
    "text/markdown",
    "text/plain",
    "text/xml",
}
ALLOWED_ATTACHMENT_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "gif", "pdf", "txt", "md", "csv", "json"}
MAX_IMAGE_DIMENSIONS = (5000, 5000)
MAX_FILENAME_LENGTH = 120
ATTACHMENT_RATE_LIMIT_SECONDS = 5

_MOD_FIPE_PCT = {
    # Pesos CONSERVADORES de valor RETIDO em revenda para itens documentados,
    # baseados no comportamento tipico do mercado brasileiro: a maioria dos
    # mods NAO repassa o custo (audio/estetica raramente agregam; performance
    # pode ajudar comprador entusiasta mas penaliza o comprador geral). Sao
    # estimativas de mercado, NAO refletem a Tabela FIPE (que e de fabrica).
    # Calibrar conforme dados reais de transacao.
    "motor": 0.04, "turbo": 0.05, "suspensao": 0.02, "freios": 0.02,
    "rodas": 0.015, "pneus": 0.01, "escapamento": 0.015, "eletronica": 0.02,
    "som": 0.005, "estetica": 0.005, "interna": 0.01, "outros": 0.01,
}
# Teto de valorizacao total para evitar inflacao irrealista do valor.
_MOD_FIPE_PCT_MAX = 0.12

# Aviso exibido junto ao valor estimado: deixa claro que NAO e avaliacao oficial.
FIPE_AJUSTADA_DISCLAIMER = (
    "Valor estimado de mercado com base na Tabela FIPE e/ou precos de anuncios "
    "reais, ajustado por itens documentados. Nao e avaliacao oficial e nao "
    "substitui pericia para venda, seguro ou financiamento."
)

_SUGESTAO_PADRAO = (
    "Revisao preventiva sugerida: troca de oleo e filtros, inspecao de freios e "
    "pneus, verificacao de fluidos e da bateria. Confirme em uma oficina de confianca."
)
_FORBIDDEN_PATTERNS = ("http://", "https://", "www.")
_REFUSAL_PATTERNS = ("nao posso", "i cannot", "desculpe, mas", "como ia", "não posso")

# Ordem de carga. ``pages_static`` por último: contém o catch-all ``/<path:path>``.
_SPLIT_MODULES = (
    "pages_users",
    "pages_vehicles",
    "pages_modpassport",
    "pages_maintenance",
    "pages_chat",
    "pages_videos",
    "pages_misc",
    "pages_static",
)

# Sanity: número de rotas esperado após a carga (41). Se algum split falhar,
# o total cai e o erro fica explícito no log em vez de silencioso.
_EXPECTED_ROUTE_COUNT = 41


def _load_split_modules():
    """Executa cada split no namespace deste módulo.

    Falhas são isoladas por módulo (log com traceback) em vez de derrubar
    o import inteiro sem diagnóstico. Ao final, valida a contagem de rotas
    e falha alto se ``pages_bp`` terminou sem nenhuma rota.
    """
    loaded = []
    failed = {}
    split_dir = os.path.join(os.path.dirname(__file__), "pages_split")
    for mod in _SPLIT_MODULES:
        path = os.path.join(split_dir, mod + ".py")
        try:
            with open(path, "r", encoding="utf-8") as fh:
                code = fh.read()
            exec(compile(code, path, "exec"), globals())  # noqa: S102 — arquivos internos versionados
            loaded.append(mod)
        except Exception:
            logger.exception("Falha ao carregar split %s; rotas desse módulo indisponíveis", mod)
            failed[mod] = True
    total = len(getattr(pages_bp, "deferred_functions", []) or [])
    # Flask <3 conta via deferred_functions; fallback: url_map só existe com app.
    logger.info("pages splits carregados: %s (falhas: %s, deferred: %d)",
                ",".join(loaded), ",".join(failed) or "nenhuma", total)
    if not loaded:
        raise RuntimeError("Nenhum split de routes/pages.py foi carregado; API indisponível.")
    if len(failed) == 0 and total and total < _EXPECTED_ROUTE_COUNT:
        logger.warning("Rotas pages abaixo do esperado: %d < %d", total, _EXPECTED_ROUTE_COUNT)
    return {"loaded": loaded, "failed": sorted(failed)}


_SPLIT_STATUS = _load_split_modules()


def get_split_status():
    """Diagnóstico da carga (útil em /health ou debug)."""
    return dict(_SPLIT_STATUS)


# Re-exports explícitos: o que testes e websocket_handler importam deste módulo.
# (Os nomes vêm dos splits via exec; a lista abaixo documenta o contrato.)
__all__ = [
    "pages_bp",
    "logger",
    "get_split_status",
    # users
    "get_user_by_id",
    "invalid_session_response",
    "ensure_premium_user",
    "ensure_maintenance_access",
    # chat
    "chat",
    "handle_voice",
    "parse_chat_attachment",
    "generate_assistant_payload",
    "get_optional_user_id",
    "normalize_guest_id",
    "hash_guest_id",
    "reserve_guest_message",
    "normalize_client_history",
    "load_user_chat_context",
    "select_recent_chat_history",
    "build_user_chat_data_context",
    "is_generic_chat_message",
    "normalize_chat_text",
    "build_spending_summary",
    "get_chat_history",
    "list_chat_conversations",
    "sync_guest_chat",
    "_emit_usage_events",
    "_emit_free_limit_reached",
    "_is_effective_premium",
    "get_free_chat_usage_month",
    # vehicles
    "add_veiculo",
    "list_veiculos",
    "upload_veiculo_foto",
    "serve_veiculo_foto",
    "edit_veiculo",
    "delete_veiculo",
    "get_vehicle_reference_images",
    "seed_vehicle_photo_if_missing",
    # mod passport
    "calcular_fipe_ajustada",
    # maintenance
    "register_maintenance_history",
    "list_maintenance_history",
    "update_maintenance_history",
    "delete_maintenance_history",
    "run_maintenance_email_dispatch",
    # videos / misc
    "get_videos",
    "add_video",
    "delete_video",
    "get_video_library",
    "generate_report",
    # constantes
    "GUEST_CHAT_LIMIT",
    "FREE_MONTHLY_CHAT_LIMIT",
    "FREE_MAINTENANCE_LIMIT",
    "MAX_ATTACHMENT_BYTES",
    "FIPE_AJUSTADA_DISCLAIMER",
]
