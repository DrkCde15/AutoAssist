import os
import logging
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from extensions import limiter
from utils.email import enviar_email
from .database import get_db, insert_get_id, is_valid_email_domain
from .analytics import record_analytics_event

marketing_bp = Blueprint("marketing", __name__)
logger = logging.getLogger(__name__)


def _frontend_base_url_for_email() -> str:
    is_production = os.getenv("FLASK_ENV") == "production"
    env_key = "URL_PROD" if is_production else "URL_DEV"
    frontend_env = (os.getenv(env_key) or os.getenv("URL_PROD") or os.getenv("URL_DEV") or "").strip()
    if not frontend_env:
        return "/"
    return frontend_env if frontend_env.endswith("/") else f"{frontend_env}/"


def _build_waitlist_email_html(nome: str, lead_magnet: str, frontend_base: str) -> str:
    first = ""
    if nome:
        first = nome.split()[0].capitalize()
    title_suffix = f", {first}" if first else ""
    cadastro_link = f"{frontend_base}cadastro.html"
    benefit = (
        "diagnósticos com a NOG, alertas de manutenção e a tabela FIPE do seu carro"
        if lead_magnet == "waitlist"
        else "novidades e novos recursos do AutoAssist"
    )
    return f"""
        <h2 style="margin-top:0;color:#111827;font-size:20px;">Obrigado pelo interesse{title_suffix}!</h2>
        <p style="color:#4b5563;font-size:16px;margin-bottom:20px;">
            Você entrou para a lista de quem quer cuidar melhor do carro. Em breve trazemos
            {benefit} antes de todo mundo.
        </p>
        <p style="color:#4b5563;font-size:15px;margin-bottom:8px;">
            Já aproveite agora, sem pagar nada:
        </p>
        <ul style="color:#4b5563;font-size:15px;line-height:1.7;padding-left:20px;margin-top:0;">
            <li>30 consultas gratuitas por mês com a NOG (IA do carro);</li>
            <li>Raio-X do carro por foto (ferrugem, vazamentos, desalinhamentos);</li>
            <li>Busca de oficinas próximas e agenda de eventos automotivos.</li>
        </ul>
        <div style="text-align:center;margin:25px 0;">
            <a href="{cadastro_link}" style="display:inline-block;padding:14px 28px;background-color:#2563eb;color:#ffffff;text-decoration:none;border-radius:8px;font-weight:bold;font-size:16px;">Criar minha conta grátis</a>
        </div>
    """


def send_lead_welcome_email(lead_id: int) -> bool:
    """Envia o e-mail de boas-vindas de um lead capturado (rodado via RQ)."""
    try:
        with get_db() as (cursor, conn):
            cursor.execute(
                "SELECT id, nome, email, lead_magnet FROM leads WHERE id = %s",
                (lead_id,),
            )
            lead = cursor.fetchone()
        if not lead:
            return False
        frontend_base = _frontend_base_url_for_email()
        html = _build_waitlist_email_html(
            lead.get("nome") or "",
            lead.get("lead_magnet") or "waitlist",
            frontend_base,
        )
        return bool(enviar_email(lead["email"], "AutoAssist: você está na lista!", html))
    except Exception as exc:
        logger.warning("Falha ao enviar e-mail de lead (id=%s): %s", lead_id, exc)
        return False


def _enqueue_lead_email(lead_id: int):
    try:
        from rq import Queue
        from redis import Redis
        redis_url = os.getenv("REDIS_URL") or os.getenv("RATELIMIT_STORAGE_URI")
        if redis_url and redis_url != "memory://":
            conn = Redis.from_url(redis_url)
            Queue("default", connection=conn).enqueue(
                "tasks.send_lead_welcome_email", lead_id, timeout=120
            )
            return
    except Exception:
        pass
    # Fallback sem Redis: melhor esforço síncrono (não bloqueia a resposta).
    try:
        send_lead_welcome_email(lead_id)
    except Exception as exc:
        logger.warning("Falha síncrona ao enviar e-mail de lead: %s", exc)


@marketing_bp.route("/api/waitlist", methods=["POST"])
@limiter.limit("10 per hour")
def capture_lead():
    """Captura um lead não-logado (topo de funil / aquisição).

    Não obriga cadastro: só nome + e-mail. Guarda atribuição UTM para medir
    de onde vieram os leads. Se o e-mail já pertence a um usuário, apenas
    informa (não cria duplicata).
    """
    data = request.get_json(silent=True) or {}
    nome = (data.get("nome") or "").strip()
    email = (data.get("email") or "").strip().lower()
    lead_magnet = (data.get("lead_magnet") or "waitlist").strip()[:60] or "waitlist"

    anonymous_id = ((data.get("anonymous_id") or "").strip()[:80]) or None
    utm_source = (data.get("utm_source") or "").strip()[:120] or None
    utm_medium = (data.get("utm_medium") or "").strip()[:120] or None
    utm_campaign = (data.get("utm_campaign") or "").strip()[:120] or None
    utm_term = (data.get("utm_term") or "").strip()[:120] or None
    utm_content = (data.get("utm_content") or "").strip()[:120] or None
    initial_referrer = (
        (data.get("initial_referrer") or data.get("referrer") or "").strip()[:500] or None
    )
    referred_by = (data.get("referred_by") or "").strip().upper()[:20] or None

    if not email:
        return jsonify(error="Informe seu e-mail."), 400
    if not is_valid_email_domain(email):
        return jsonify(error="Insira um endereço de email válido"), 400

    try:
        with get_db() as (cursor, conn):
            # Já é usuário? Apenas informa (evita duplicar/contar lead falso).
            cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
            existing_user = cursor.fetchone()
            if existing_user:
                return jsonify(
                    success=True,
                    already_user=True,
                    message="Você já tem uma conta no AutoAssist!",
                ), 200

            cursor.execute("SELECT id FROM leads WHERE email = %s", (email,))
            existing_lead = cursor.fetchone()
            if existing_lead:
                # Idempotente: enriquece a atribuição se vier de nova campanha.
                try:
                    cursor.execute(
                        """
                        UPDATE leads
                        SET anonymous_id = COALESCE(anonymous_id, %s),
                            utm_source = COALESCE(utm_source, %s),
                            utm_medium = COALESCE(utm_medium, %s),
                            utm_campaign = COALESCE(utm_campaign, %s),
                            referred_by = COALESCE(referred_by, %s)
                        WHERE id = %s
                        """,
                        (anonymous_id, utm_source, utm_medium, utm_campaign, referred_by, existing_lead["id"]),
                    )
                except Exception:
                    pass
                return jsonify(success=True, already_lead=True, message="E-mail já registrado. Em breve falaremos com você!"), 200

            lead_id = insert_get_id(
                cursor,
                """
                INSERT INTO leads (
                    nome, email, anonymous_id, utm_source, utm_medium, utm_campaign,
                    utm_term, utm_content, initial_referrer, referred_by, lead_magnet
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    nome or None, email, anonymous_id, utm_source, utm_medium, utm_campaign,
                    utm_term, utm_content, initial_referrer, referred_by, lead_magnet,
                ),
            )

        # Evento de analytics (topo de funil) para o relatório de aquisição.
        try:
            record_analytics_event(
                "lead_capture",
                anonymous_id=anonymous_id,
                path="/api/waitlist",
                metadata={
                    "lead_magnet": lead_magnet,
                    "referrer": initial_referrer,
                    "utm_source": utm_source,
                    "utm_medium": utm_medium,
                    "utm_campaign": utm_campaign,
                },
            )
        except Exception as evt_exc:
            logger.warning("Falha ao emitir evento lead_capture: %s", evt_exc)

        _enqueue_lead_email(lead_id)

        return jsonify(success=True, message="E-mail registrado! Verifique sua caixa de entrada."), 201
    except Exception as e:
        logger.error("Erro ao capturar lead: %s", e)
        return jsonify(error="Erro ao registrar interesse. Tente novamente."), 500


@marketing_bp.route("/api/admin/leads", methods=["GET"])
@limiter.limit("30 per minute")
@jwt_required()
def list_leads():
    """Lista leads capturados + métricas de conversão (acesso restrito a admin)."""
    admin_id = get_jwt_identity()
    try:
        with get_db() as (cursor, conn):
            cursor.execute("SELECT is_admin FROM users WHERE id = %s", (admin_id,))
            row = cursor.fetchone()
        if not row or not row.get("is_admin"):
            return jsonify(error="Acesso restrito."), 403

        limit = min(int(request.args.get("limit", "200")), 1000)
        with get_db() as (cursor, conn):
            cursor.execute(
                """
                SELECT id, nome, email, utm_source, utm_medium, utm_campaign,
                       referred_by, lead_magnet, converted_user_id, created_at
                FROM leads
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            leads = cursor.fetchall() or []

            cursor.execute(
                "SELECT COUNT(*) AS total FROM leads",
            )
            total = (cursor.fetchone() or {}).get("total", 0)
            cursor.execute(
                "SELECT COUNT(*) AS conv FROM leads WHERE converted_user_id IS NOT NULL",
            )
            converted = (cursor.fetchone() or {}).get("conv", 0)
            cursor.execute(
                "SELECT COUNT(DISTINCT utm_source) AS src FROM leads WHERE utm_source IS NOT NULL AND utm_source <> ''",
            )
            sources = (cursor.fetchone() or {}).get("src", 0)

        return jsonify(
            total=total,
            converted=converted,
            distinct_sources=sources,
            leads=leads,
        ), 200
    except Exception as e:
        logger.error("Erro ao listar leads: %s", e)
        return jsonify(error="Erro interno."), 500
