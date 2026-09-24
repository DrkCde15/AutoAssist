"""
B2B API - Diagnóstico por foto como API assinável (clientes corporativos).

Autenticação: header `X-API-Key` com chave gerada via `POST /api/b2b/keys`
(admin, protegida por B2B_ADMIN_SECRET). A chave é exibida UMA vez; no banco
fica apenas o hash SHA-256. Comparação em tempo constante (hmac.compare_digest).
Rate limit por cliente (minuto) com contador atômico no Redis (fallback local).
"""
import hashlib
import hmac
import io
import logging
import os
import uuid
import secrets
import time

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from fpdf import FPDF

from routes.database import get_db
from services.vision_ai import analisar_imagem
from services.cakto import CaktoService
from utils.cache import get_redis_client
from utils.turnstile import turnstile_required
from extensions import limiter

b2b_bp = Blueprint("b2b_bp", __name__)
logger = logging.getLogger(__name__)

API_KEY_HEADER = "X-API-Key"
FALLBACK_LIMIT = 30  # requests/min por cliente (sem Redis / sem valor configurado)
_local_rate = {}  # client_id -> (janela, contagem) para fallback sem Redis
MAX_IMAGE_B64 = 15 * 1024 * 1024  # 15 MB base64 (~11 MB binário)

# P1-2: tiers de autoatendimento B2B (quota de requisições por chave).
# requests_limit == 0 significa ilimitado (chaves criadas via admin).
B2B_PLANS = {
    "trial":   {"requests_limit": 100,   "rate_limit_per_min": 10,  "label": "Trial gratuito", "amount": 0,     "currency": "BRL", "interval": "month"},
    "pro_1k":  {"requests_limit": 1000,  "rate_limit_per_min": 30,  "label": "Pro 1k",         "amount": 99.00, "currency": "BRL", "interval": "month"},
    "pro_5k":  {"requests_limit": 5000,  "rate_limit_per_min": 60,  "label": "Pro 5k",         "amount": 399.00, "currency": "BRL", "interval": "month"},
    "pro_20k": {"requests_limit": 20000, "rate_limit_per_min": 120, "label": "Pro 20k",        "amount": 999.00, "currency": "BRL", "interval": "month"},
}
# URLs de checkout Cakto por tier (Opção A: preço distinto por plano).
# Prioriza variaveis de ambiente; fallback para os links cadastrados em producao.
CAKTO_B2B_URLS = {
    "pro_1k":  os.getenv("CAKTO_B2B_1K_URL")  or "https://pay.cakto.com.br/tqsqfbm_1063481",
    "pro_5k":  os.getenv("CAKTO_B2B_5K_URL")  or "https://pay.cakto.com.br/9d8ewr2_1063487",
    "pro_20k": os.getenv("CAKTO_B2B_20K_URL") or "https://pay.cakto.com.br/pw29nsi_1063494",
}
DEFAULT_B2B_PLAN = "trial"


def _hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def _api_key_prefix(raw_key: str) -> str:
    return raw_key[:12]


def authenticate_api_key():
    """Valida o header X-API-Key. Retorna dict do cliente ou None."""
    raw_key = (request.headers.get(API_KEY_HEADER) or "").strip()
    if not raw_key or len(raw_key) < 16:
        return None
    key_hash = _hash_api_key(raw_key)
    try:
        with get_db() as (cursor, conn):
            cursor.execute(
                "SELECT id, nome, api_key_hash, is_active, rate_limit_per_min "
                "FROM api_clients WHERE api_key_hash = %s",
                (key_hash,),
            )
            client = cursor.fetchone()

        if not client:
            return None
        # Double-check: garante comparação em tempo constante mesmo via índice
        if not hmac.compare_digest(client["api_key_hash"], key_hash):
            return None
        if not client.get("is_active"):
            return None
        return dict(client)
    except Exception as exc:
        logger.error("Erro ao autenticar API key: %s", exc, exc_info=True)
        return None


def check_rate_limit(client_id: int, limit_per_min: int) -> bool:
    """Contador deslizante simples por janela de 60s. True = pode passar."""
    limit = int(limit_per_min or FALLBACK_LIMIT)
    redis = get_redis_client()
    now = int(time.time())
    window = now // 60
    key = f"b2b:rate:{client_id}:{window}"
    if redis is not None:
        try:
            count = redis.incr(key)
            if count == 1:
                redis.expire(key, 90)
            return count <= limit
        except Exception:
            pass
    # Fallback local (por processo)
    prev = _local_rate.get(client_id)
    if not prev or prev[0] != window:
        _local_rate[client_id] = (window, 1)
        return True
    prev = _local_rate[client_id]
    if prev[1] >= limit:
        return False
    _local_rate[client_id] = (window, prev[1] + 1)
    return True


def log_usage(client_id: int, endpoint: str, status_code: int):
    try:
        with get_db() as (cursor, conn):
            cursor.execute(
                "INSERT INTO api_usage_logs (client_id, endpoint, status_code) "
                "VALUES (%s, %s, %s)",
                (client_id, endpoint, status_code),
            )
            cursor.execute(
                "UPDATE api_clients SET last_used_at = NOW() WHERE id = %s",
                (client_id,),
            )
    except Exception as exc:
        logger.warning("Falha ao logar uso B2B: %s", exc)


def _build_laudo_pdf(cliente_nome: str, texto_laudo: str) -> bytes:
    """Gera o PDF do laudo em memória (estilo padronizado AutoAssist)."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 15)
    pdf.set_text_color(59, 130, 246)
    pdf.cell(0, 10, "AutoAssist IA - Laudo Tecnico (B2B)", 0, 1, "C")
    pdf.ln(5)

    pdf.set_font("Arial", "B", 12)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(0, 8, "Cliente:", 0, 1)
    pdf.set_font("Arial", "", 11)
    pdf.cell(0, 7, cliente_nome, 0, 1)
    from datetime import datetime
    pdf.cell(0, 7, f"Emitido em: {datetime.now().strftime('%d/%m/%Y %H:%M')}", 0, 1)
    pdf.ln(4)

    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 8, "Diagnostico (IA):", 0, 1)
    pdf.ln(2)
    pdf.set_font("Arial", "", 11)
    texto_limpo = (
        texto_laudo.replace("–", "-").replace("—", "-")
        .replace("“", '"').replace("”", '"')
        .replace("‘", "'").replace("’", "'")
    )
    texto_limpo = texto_limpo.encode("latin-1", "ignore").decode("latin-1")
    pdf.multi_cell(0, 7, texto_limpo)

    pdf.ln(8)
    pdf.set_font("Arial", "I", 9)
    pdf.set_text_color(200, 50, 50)
    pdf.multi_cell(
        0, 5,
        "AVISO: Laudo gerado por Inteligencia Artificial. Nao substitui "
        "inspecao mecanica presencial.",
    )
    return pdf.output(dest="S").encode("latin-1")


@b2b_bp.route("/api/b2b/diagnosis", methods=["POST"])
def b2b_diagnosis():
    client = authenticate_api_key()
    if not client:
        return jsonify(error="API key invalida ou inativa."), 401

    if not check_rate_limit(client["id"], client.get("rate_limit_per_min")):
        log_usage(client["id"], "/api/b2b/diagnosis", 429)
        return jsonify(error="Limite de requisicoes excedido."), 429

    # P1-2: quota de volume por chave (requests_limit == 0 = ilimitado).
    req_limit = client.get("requests_limit") or 0
    if req_limit and (client.get("requests_used") or 0) >= req_limit:
        log_usage(client["id"], "/api/b2b/diagnosis", 429)
        return jsonify(error="Cota de requisicoes esgotada. Faca upgrade do plano B2B.", code="quota_exhausted"), 429


    data = request.get_json(silent=True) or {}
    # P1: validação tipada (pydantic) — mantém chaves legadas image/image_b64
    try:
        from schemas.b2b import B2BDiagnosisInput as _B2BInput
        parsed = _B2BInput.model_validate(data)
        image_b64 = parsed.resolved_image()
        pergunta = parsed.pergunta
        formato = parsed.formato
    except Exception as _ve:
        from pydantic import ValidationError as _VE
        if isinstance(_ve, _VE):
            log_usage(client["id"], "/api/b2b/diagnosis", 400)
            return jsonify(error="Payload inválido.", details=str(_ve)[:500]), 400
        image_b64 = (data.get("image") or data.get("image_b64") or "").strip()
        pergunta = (data.get("pergunta") or "").strip() or None
        formato = (data.get("formato") or "json").strip().lower()
    if not image_b64:
        log_usage(client["id"], "/api/b2b/diagnosis", 400)
        return jsonify(error="Campo 'image' (base64) e obrigatorio."), 400
    if len(image_b64) > MAX_IMAGE_B64:
        log_usage(client["id"], "/api/b2b/diagnosis", 413)
        return jsonify(error="Imagem muito grande (max 15MB em base64)."), 413

    if pergunta is not None and len(pergunta) > 2000:
        log_usage(client["id"], "/api/b2b/diagnosis", 400)
        return jsonify(error="Campo 'pergunta' muito longo (max 2000)."), 400

    try:
        laudo = analisar_imagem(image_b64, pergunta)
    except Exception as exc:
        logger.error("B2B: falha na analise de imagem: %s", exc, exc_info=True)
        log_usage(client["id"], "/api/b2b/diagnosis", 502)
        return jsonify(error="Falha na analise da imagem. Tente novamente."), 502

    if "não conseguiu" in laudo or "nao conseguiu" in laudo:
        log_usage(client["id"], "/api/b2b/diagnosis", 502)
        return jsonify(error=laudo), 502

    log_usage(client["id"], "/api/b2b/diagnosis", 200)
    # P1-2: contabiliza uso contra a cota do plano.
    try:
        with get_db() as (cursor, conn):
            cursor.execute(
                "UPDATE api_clients SET requests_used = requests_used + 1 WHERE id = %s",
                (client["id"],),
            )
    except Exception:
        pass

    if formato == "pdf":
        try:
            pdf_bytes = _build_laudo_pdf(client["nome"], laudo)
        except Exception as exc:
            logger.error("B2B: falha ao gerar PDF: %s", exc, exc_info=True)
            pdf_bytes = laudo.encode("latin-1", "ignore")
        from flask import send_file
        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=True,
            download_name="laudo_autoassist.pdf",
        )

    return jsonify({
        "success": True,
        "client": client["nome"],
        "formato": "json",
        "laudo": laudo,
        "aviso": "Laudo gerado por IA. Nao substitui inspecao mecanica presencial.",
    }), 200


@b2b_bp.route("/api/b2b/keys", methods=["POST"])
def create_api_key():
    """Cria uma nova API key B2B. Protegida por B2B_ADMIN_SECRET (header X-Admin-Secret)."""
    expected = (os.getenv("B2B_ADMIN_SECRET") or "").strip()
    if not expected:
        return jsonify(error="B2B_ADMIN_SECRET nao configurado."), 500
    provided = request.headers.get("X-Admin-Secret") or ""
    if not provided or not hmac.compare_digest(provided, expected):
        return jsonify(error="Acesso negado."), 403

    data = request.get_json(silent=True) or {}
    try:
        from schemas.b2b import B2BCreateKeyInput as _KeyInput
        parsed = _KeyInput.model_validate(data)
        nome = parsed.nome.strip()[:120]
        rate_limit = parsed.rate_limit_per_min
    except Exception as _ve:
        from pydantic import ValidationError as _VE
        if isinstance(_ve, _VE):
            return jsonify(error="Payload inválido.", details=str(_ve)[:500]), 400
        nome = (data.get("nome") or "").strip()[:120]
        if not nome:
            return jsonify(error="Campo 'nome' do cliente e obrigatorio."), 400
        rate_limit = data.get("rate_limit_per_min")
        try:
            rate_limit = max(1, min(int(rate_limit), 600))
        except (TypeError, ValueError):
            rate_limit = FALLBACK_LIMIT
    if not nome:
        return jsonify(error="Campo 'nome' do cliente e obrigatorio."), 400

    raw_key = f"aa_{secrets.token_urlsafe(32)}"
    key_hash = _hash_api_key(raw_key)
    try:
        with get_db() as (cursor, conn):
            cursor.execute(
                "INSERT INTO api_clients (nome, api_key_hash, api_key_prefix, rate_limit_per_min) "
                "VALUES (%s, %s, %s, %s)",
                (nome, key_hash, _api_key_prefix(raw_key), rate_limit),
            )
    except Exception as exc:
        logger.error("Erro ao criar API key: %s", exc, exc_info=True)
        return jsonify(error="Erro interno ao criar a chave."), 500

    logger.info("B2B: nova API key criada para %s (prefixo %s)", nome, _api_key_prefix(raw_key))
    return jsonify({
        "success": True,
        "client_nome": nome,
        "api_key": raw_key,   # exibida UMA vez
        "api_key_prefix": _api_key_prefix(raw_key),
        "rate_limit_per_min": rate_limit,
        "aviso": "Guarde esta chave agora: ela nao podera ser recuperada depois.",
    }), 201


@b2b_bp.route("/api/b2b/self-serve/keys", methods=["POST"])
@jwt_required()
def create_self_serve_key():
    """P1-2: usuário logado cria sua própria chave B2B (autoatendimento)."""
    user_id = get_jwt_identity()
    data = request.get_json(silent=True) or {}
    plan = (data.get("plan") or DEFAULT_B2B_PLAN)
    if plan not in B2B_PLANS:
        plan = DEFAULT_B2B_PLAN
    cfg = B2B_PLANS[plan]
    nome = (data.get("nome") or "").strip()[:120]
    if not nome:
        nome = f"Cliente B2B #{user_id}"
    raw_key = f"aa_{secrets.token_urlsafe(32)}"
    key_hash = _hash_api_key(raw_key)
    try:
        with get_db() as (cursor, conn):
            cursor.execute(
                "INSERT INTO api_clients (user_id, nome, api_key_hash, api_key_prefix, rate_limit_per_min, plan, requests_limit) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (user_id, nome, key_hash, _api_key_prefix(raw_key), cfg["rate_limit_per_min"], plan, cfg["requests_limit"]),
            )
    except Exception as exc:
        logger.error("Erro ao criar API key self-serve: %s", exc, exc_info=True)
        return jsonify(error="Erro interno ao criar a chave."), 500
    return jsonify({
        "success": True,
        "client_nome": nome,
        "plan": plan,
        "api_key": raw_key,
        "requests_limit": cfg["requests_limit"],
        "rate_limit_per_min": cfg["rate_limit_per_min"],
        "aviso": "Guarde esta chave agora: ela nao podera ser recuperada depois.",
    }), 201


def _create_pending_b2b_key(user_id, plan, nome, cfg):
    """Cria a API key B2B inativa; so passa a funcionar apos o pagamento (webhook)."""
    raw_key = f"aa_{secrets.token_urlsafe(32)}"
    key_hash = _hash_api_key(raw_key)
    try:
        with get_db() as (cursor, conn):
            cursor.execute(
                """INSERT INTO api_clients
                   (user_id, nome, api_key_hash, api_key_prefix, rate_limit_per_min, plan, requests_limit, is_active)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, FALSE)""",
                (user_id, nome, key_hash, _api_key_prefix(raw_key),
                 cfg["rate_limit_per_min"], plan, cfg["requests_limit"]),
            )
            client_id = cursor.lastrowid
        return raw_key, client_id
    except Exception as exc:
        logger.error("Erro ao criar chave B2B pendente: %s", exc, exc_info=True)
        return None, None


def _b2b_user_email(user_id):
    try:
        with get_db() as (cursor, conn):
            cursor.execute("SELECT email FROM users WHERE id = %s", (user_id,))
            row = cursor.fetchone()
        email = row.get("email") if row else None
        return str(email).strip().lower() if isinstance(email, str) and email.strip() else None
    except Exception:
        return None


def set_b2b_client_state(user_id, plan, active=True):
    """Ativa ou revoga a API key B2B do usuario conforme o evento da Cakto.

    `active=True` confirma pagamento/renovacao; `active=False` revoga em
    cancelamento/reembolso. A clausula nao filtra por is_active previo, para
    que renovacoes (ja ativas) e revogacoes funcionem corretamente.
    """
    cfg = B2B_PLANS.get(plan)
    if not cfg:
        return 0
    try:
        with get_db() as (cursor, conn):
            cursor.execute(
                """UPDATE api_clients
                   SET is_active = %s, plan = %s, requests_limit = %s
                   WHERE user_id = %s AND plan = %s
                   LIMIT 1""",
                (bool(active), plan, cfg["requests_limit"], user_id, plan),
            )
            return int(cursor.rowcount or 0)
    except Exception as exc:
        logger.error("Erro ao definir estado do cliente B2B: %s", exc, exc_info=True)
        return 0


def activate_b2b_client(user_id, plan):
    """Compatibilidade: ativa a API key B2B pendente apos confirmacao de pagamento."""
    return set_b2b_client_state(user_id, plan, active=True)


@b2b_bp.route("/api/b2b/self-serve/checkout", methods=["POST"])
@jwt_required()
def create_self_serve_checkout():
    """P1-2 + monetizacao B2B: plano pago gera pedido Cakto + API key inativa ate o pagamento."""
    user_id = get_jwt_identity()
    data = request.get_json(silent=True) or {}
    plan = (data.get("plan") or DEFAULT_B2B_PLAN)
    if plan not in B2B_PLANS:
        plan = DEFAULT_B2B_PLAN
    cfg = B2B_PLANS[plan]

    # Trial continua gratis e imediato (sem cobranca).
    if not cfg.get("amount"):
        return create_self_serve_key()

    nome = (data.get("nome") or "").strip()[:120]
    if not nome:
        nome = f"Cliente B2B #{user_id}"

    raw_key, client_id = _create_pending_b2b_key(user_id, plan, nome, cfg)
    if raw_key is None:
        return jsonify(error="Erro interno ao criar a chave B2B."), 500

    order_id = str(uuid.uuid4())
    try:
        with get_db() as (cursor, conn):
            cursor.execute(
                """INSERT INTO payments_orders
                   (id, user_id, status, plan, amount, currency, provider)
                   VALUES (%s, %s, 'pending', %s, %s, %s, 'cakto')""",
                (order_id, user_id, f"b2b_{plan}", cfg["amount"], cfg["currency"]),
            )
            conn.commit()
    except Exception as exc:
        logger.error("Erro ao criar pedido B2B: %s", exc, exc_info=True)
        return jsonify(error="Erro interno ao criar o pedido."), 500

    try:
        svc = CaktoService()
        checkout_url = svc.build_checkout_url(
            user_id=user_id,
            user_email=_b2b_user_email(user_id),
            provided_url=CAKTO_B2B_URLS.get(plan) or os.getenv("CAKTO_B2B_CHECKOUT_URL") or None,
            internal_order_id=order_id,
        )
    except Exception as exc:
        logger.error("Erro ao gerar checkout B2B: %s", exc)
        return jsonify(error="Checkout Cakto indisponivel. Configure CAKTO_B2B_CHECKOUT_URL."), 500

    return jsonify({
        "success": True,
        "plan": plan,
        "api_key": raw_key,
        "checkout_url": checkout_url,
        "order_id": order_id,
        "aviso": "Chave criada. Conclua o pagamento para ativa-la.",
    }), 201


def _b2b_admin_user_id():
    """Retorna o id do usuario se for admin, senao None."""
    try:
        from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity
        verify_jwt_in_request()
        uid = get_jwt_identity()
    except Exception:
        return None
    try:
        with get_db() as (cursor, conn):
            cursor.execute("SELECT is_admin FROM users WHERE id = %s", (uid,))
            row = cursor.fetchone()
        if row and row.get("is_admin"):
            return uid
    except Exception:
        return None
    return None


def _clean(value, max_len):
    if value is None:
        return ""
    return " ".join(str(value).split())[:max_len]


@b2b_bp.route("/api/b2b/leads", methods=["POST"])
@limiter.limit("10 per minute")
@turnstile_required(action="b2b_lead")
def post_b2b_lead():
    """Captura um lead do formulario publico da pagina B2B."""
    data = request.get_json(silent=True) or {}
    nome = _clean(data.get("nome"), 120)
    email = _clean(data.get("email"), 120)
    if not nome or not email:
        return jsonify(error="nome e email sao obrigatorios."), 400
    empresa = _clean(data.get("empresa"), 120)
    telefone = _clean(data.get("telefone"), 30)
    mensagem = _clean(data.get("mensagem"), 2000)
    origem = _clean(data.get("origem") or "site_b2b", 60)
    from utils.abuse_monitor import monitor_public_ingest
    monitor_public_ingest("b2b_leads", limit=50)
    try:
        with get_db() as (cursor, conn):
            cursor.execute(
                """
                INSERT INTO b2b_leads (nome, email, empresa, telefone, mensagem, origem)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (nome, email, empresa, telefone, mensagem, origem),
            )
        return jsonify(message="Recebemos seu contato! Nossa equipe B2B entrara em contato."), 201
    except Exception as e:
        logger.error("Erro ao salvar lead B2B: %s", e, exc_info=True)
        return jsonify(error="Erro interno ao enviar contato."), 500


@b2b_bp.route("/api/admin/b2b/leads", methods=["GET"])
@limiter.limit("20 per minute")
def list_b2b_leads():
    if _b2b_admin_user_id() is None:
        return jsonify(error="Acesso restrito."), 403
    try:
        with get_db() as (cursor, conn):
            cursor.execute(
                "SELECT id, nome, email, empresa, telefone, mensagem, origem, created_at "
                "FROM b2b_leads ORDER BY created_at DESC LIMIT 200"
            )
            leads = cursor.fetchall()
        return jsonify(leads=leads), 200
    except Exception as e:
        logger.error("Erro ao listar leads B2B: %s", e, exc_info=True)
        return jsonify(error="Erro interno."), 500


@b2b_bp.route("/api/b2b/usage", methods=["GET"])
@jwt_required()
def b2b_usage():
    """Uso da API B2B do usuario logado (quota por tier)."""
    user_id = get_jwt_identity()
    try:
        with get_db() as (cursor, conn):
            cursor.execute(
                "SELECT id, nome, plan, requests_limit, requests_used, rate_limit_per_min, "
                "is_active, last_used_at FROM api_clients WHERE user_id = %s ORDER BY id DESC LIMIT 20",
                (user_id,),
            )
            clients = cursor.fetchall()
        out = []
        for c in clients:
            limit = c.get("requests_limit") or 0
            used = c.get("requests_used") or 0
            out.append({
                "client_id": c.get("id"),
                "nome": c.get("nome"),
                "plan": c.get("plan"),
                "requests_limit": limit,
                "requests_used": used,
                "requests_restantes": (limit - used) if limit else None,
                "rate_limit_per_min": c.get("rate_limit_per_min"),
                "is_active": c.get("is_active"),
                "last_used_at": c.get("last_used_at").isoformat() if c.get("last_used_at") else None,
            })
        return jsonify(clients=out), 200
    except Exception as e:
        logger.error("Erro usage B2B: %s", e, exc_info=True)
        return jsonify(error="Erro interno."), 500


@b2b_bp.route("/api/b2b/webhook/usage", methods=["POST"])
def b2b_webhook_usage():
    """Webhook para receber eventos de uso de integracoes externas (best-effort).

    Corpo esperado: {"api_key": "...", "endpoint": "...", "status": 200}
    Apenas registra o uso; nao altera quota (quota e controlada na chamada real).
    """
    data = request.get_json(silent=True) or {}
    raw_key = (data.get("api_key") or "").strip()
    if not raw_key:
        return jsonify(error="api_key obrigatorio."), 400
    endpoint = (data.get("endpoint") or "/webhook").strip()
    status = int(data.get("status") or 200)
    client = authenticate_api_key()
    if not client:
        return jsonify(error="api_key invalida."), 401
    try:
        log_usage(client["id"], endpoint, status)
    except Exception as e:
        logger.warning("Webhook usage falhou: %s", e)
    return jsonify(success=True), 200
