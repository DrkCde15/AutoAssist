import os
import base64
import logging
import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Carrega variaveis de ambiente
basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, "..", ".env"))

EMAIL_REMETENTE = os.getenv("EMAIL_REMETENTE")
EMAIL_SENHA_APP = os.getenv("EMAIL_SENHA_APP")
EMAIL_FROM = (os.getenv("EMAIL_FROM") or EMAIL_REMETENTE or "").strip()
EMAIL_FROM_NAME = (os.getenv("EMAIL_FROM_NAME") or "AutoAssist").strip()
EMAIL_PROVIDER = (os.getenv("EMAIL_PROVIDER") or "smtp").strip().lower()
SMTP_TIMEOUT_SECONDS = int(os.getenv("SMTP_TIMEOUT_SECONDS", "8"))
EMAIL_API_TIMEOUT_SECONDS = int(os.getenv("EMAIL_API_TIMEOUT_SECONDS", "8"))
EMAIL_API_CONNECT_TIMEOUT_SECONDS = int(os.getenv("EMAIL_API_CONNECT_TIMEOUT_SECONDS", "5"))
EMAIL_API_RETRIES = int(os.getenv("EMAIL_API_RETRIES", "2"))

# Mailtrap & Generic SMTP configurations
MAILTRAP_API_TOKEN = (os.getenv("MAILTRAP_API_TOKEN") or EMAIL_SENHA_APP or "").strip()
MAILTRAP_SANDBOX_ID = (os.getenv("MAILTRAP_SANDBOX_ID") or "").strip()
SMTP_HOST = (os.getenv("SMTP_HOST") or "smtp.gmail.com").strip()
try:
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
except ValueError:
    SMTP_PORT = 587

# Google Apps Script configurations
GOOGLE_SCRIPT_URL = (os.getenv("GOOGLE_SCRIPT_URL") or "").strip()
GOOGLE_SCRIPT_SECRET = (os.getenv("GOOGLE_SCRIPT_SECRET") or "").strip()

GMAIL_OAUTH_CLIENT_ID = (
    os.getenv("GMAIL_OAUTH_CLIENT_ID")
    or os.getenv("GOOGLE_CLIENT_ID")
    or ""
).strip()
GMAIL_OAUTH_CLIENT_SECRET = (
    os.getenv("GMAIL_OAUTH_CLIENT_SECRET")
    or os.getenv("GOOGLE_CLIENT_SECRET")
    or ""
).strip()
GMAIL_OAUTH_REFRESH_TOKEN = (os.getenv("GMAIL_OAUTH_REFRESH_TOKEN") or "").strip()
GMAIL_OAUTH_TOKEN_URI = (
    os.getenv("GMAIL_OAUTH_TOKEN_URI")
    or "https://oauth2.googleapis.com/token"
).strip()

_gmail_access_token = None
_gmail_token_expires_at = 0


def _post_with_retry(url: str, payload: dict, headers: dict):
    attempts = max(1, EMAIL_API_RETRIES + 1)
    last_exc = None
    for attempt in range(1, attempts + 1):
        try:
            return requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=(EMAIL_API_CONNECT_TIMEOUT_SECONDS, EMAIL_API_TIMEOUT_SECONDS),
            )
        except requests.exceptions.Timeout as exc:
            last_exc = exc
            if attempt < attempts:
                time.sleep(0.6 * attempt)
                continue
            raise
    if last_exc:
        raise last_exc
    raise RuntimeError("Falha inesperada no envio HTTP")


def _base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _get_gmail_access_token() -> str | None:
    global _gmail_access_token, _gmail_token_expires_at

    now = int(time.time())
    if _gmail_access_token and now < (_gmail_token_expires_at - 60):
        return _gmail_access_token

    if not all(
        [
            GMAIL_OAUTH_CLIENT_ID,
            GMAIL_OAUTH_CLIENT_SECRET,
            GMAIL_OAUTH_REFRESH_TOKEN,
        ]
    ):
        logger.warning(
            "Gmail OAuth nao configurado: defina GMAIL_OAUTH_CLIENT_ID, "
            "GMAIL_OAUTH_CLIENT_SECRET e GMAIL_OAUTH_REFRESH_TOKEN."
        )
        return None

    try:
        resp = requests.post(
            GMAIL_OAUTH_TOKEN_URI,
            data={
                "client_id": GMAIL_OAUTH_CLIENT_ID,
                "client_secret": GMAIL_OAUTH_CLIENT_SECRET,
                "refresh_token": GMAIL_OAUTH_REFRESH_TOKEN,
                "grant_type": "refresh_token",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=(EMAIL_API_CONNECT_TIMEOUT_SECONDS, EMAIL_API_TIMEOUT_SECONDS),
        )
    except requests.exceptions.RequestException as exc:
        logger.warning("Erro ao renovar token OAuth do Gmail: %s", exc)
        return None

    if not 200 <= resp.status_code < 300:
        logger.warning(
            "Erro ao renovar token OAuth do Gmail: HTTP %s - %s",
            resp.status_code,
            resp.text,
        )
        return None

    data = resp.json()
    _gmail_access_token = data.get("access_token")
    if not _gmail_access_token:
        logger.warning("Resposta OAuth do Gmail sem access_token.")
        return None

    _gmail_token_expires_at = int(time.time()) + int(data.get("expires_in", 3600))
    return _gmail_access_token


def _wrap_email_html(content_html: str) -> str:
    """Template base premium do AutoAssist."""
    template = """
    <div style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; padding: 30px; background-color: #f3f4f6; min-height: 100%;">
        <div style="max-width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 16px; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);">
            <div style="background: linear-gradient(135deg, #2563eb, #1d4ed8); padding: 30px; text-align: center;">
                <h1 style="color: #ffffff; margin: 0; font-size: 24px; letter-spacing: 1px;">AutoAssist</h1>
            </div>
            <div style="padding: 40px 30px; line-height: 1.6; color: #374151;">
                {{CONTENT}}
            </div>
            <div style="padding: 20px; background-color: #f9fafb; text-align: center; border-top: 1px solid #e5e7eb;">
                <p style="margin: 0; font-size: 12px; color: #9ca3af;">
                    &copy; 2026 AutoAssist - Seu assistente automotivo inteligente.<br>
                    Este e um e-mail automatico, por favor nao responda.
                </p>
            </div>
        </div>
    </div>
    """
    return template.replace("{{CONTENT}}", content_html or "")


def _from_string() -> str:
    if EMAIL_FROM_NAME and EMAIL_FROM:
        return f"{EMAIL_FROM_NAME} <{EMAIL_FROM}>"
    return EMAIL_FROM or EMAIL_REMETENTE or ""


def _send_via_gmail_api(destinatario: str, assunto: str, html_final: str) -> bool:
    token = _get_gmail_access_token()
    if not token:
        return False
    if not (EMAIL_FROM or EMAIL_REMETENTE):
        logger.warning("Gmail API nao configurada: defina EMAIL_FROM ou EMAIL_REMETENTE.")
        return False

    msg = MIMEMultipart("alternative")
    msg["From"] = _from_string() or EMAIL_REMETENTE
    msg["To"] = destinatario
    msg["Subject"] = assunto
    msg.attach(MIMEText(html_final, "html", "utf-8"))

    payload = {"raw": _base64url(msg.as_bytes())}
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    resp = _post_with_retry(
        "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
        payload,
        headers,
    )
    if 200 <= resp.status_code < 300:
        return True
    logger.warning("Erro ao enviar e-mail via Gmail API: HTTP %s - %s", resp.status_code, resp.text)
    return False


def _send_via_smtp(destinatario: str, assunto: str, html_final: str) -> bool:
    if not EMAIL_REMETENTE or not EMAIL_SENHA_APP:
        logger.warning("SMTP nao configurado: defina EMAIL_REMETENTE e EMAIL_SENHA_APP.")
        return False

    msg = MIMEMultipart()
    msg["From"] = _from_string() or EMAIL_REMETENTE
    msg["To"] = destinatario
    msg["Subject"] = assunto
    msg.attach(MIMEText(html_final, "html"))

    try:
        logger.info("Tentando enviar e-mail SMTP (%s:%s) para: %s", SMTP_HOST, SMTP_PORT, destinatario)
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT_SECONDS) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(EMAIL_REMETENTE, EMAIL_SENHA_APP)
            server.send_message(msg)
        return True
    except Exception as exc:
        logger.warning("Erro ao enviar e-mail via SMTP: %s", exc)
        return False


def _send_via_mailtrap(destinatario: str, assunto: str, html_final: str) -> bool:
    token = MAILTRAP_API_TOKEN
    if not token:
        logger.warning("Mailtrap nao configurado: defina MAILTRAP_API_TOKEN ou EMAIL_SENHA_APP.")
        return False

    sender_email = EMAIL_FROM or "hello@demomailtrap.co"
    sender_name = EMAIL_FROM_NAME or "AutoAssist"

    if MAILTRAP_SANDBOX_ID:
        url = f"https://sandbox.api.mailtrap.io/api/send/{MAILTRAP_SANDBOX_ID}"
    else:
        url = "https://send.api.mailtrap.io/api/send"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    # Extrai o texto limpo para o campo text se necessário, ou usa um fallback
    text_content = f"Alerta do AutoAssist: {assunto}"

    payload = {
        "from": {
            "email": sender_email,
            "name": sender_name
        },
        "to": [
            {
                "email": destinatario
            }
        ],
        "subject": assunto,
        "html": html_final,
        "text": text_content,
        "category": "AutoAssist Alert"
    }

    try:
        logger.info("Enviando e-mail via Mailtrap API para: %s (Sandbox ID: %s)", destinatario, MAILTRAP_SANDBOX_ID or "Nao definido")
        resp = _post_with_retry(url, payload, headers)
        if 200 <= resp.status_code < 300:
            logger.info("E-mail enviado com sucesso via Mailtrap para %s", destinatario)
            return True
        logger.warning("Erro ao enviar e-mail via Mailtrap: HTTP %s - %s", resp.status_code, resp.text)
        return False
    except Exception as exc:
        logger.warning("Erro ao enviar e-mail via Mailtrap: %s", exc)
        return False


def _send_via_google_script(destinatario: str, assunto: str, html_final: str) -> bool:
    if not GOOGLE_SCRIPT_URL:
        logger.warning("Google Apps Script nao configurado: defina GOOGLE_SCRIPT_URL.")
        return False

    payload = {
        "secret": GOOGLE_SCRIPT_SECRET,
        "to": destinatario,
        "subject": assunto,
        "html": html_final
    }
    
    headers = {"Content-Type": "application/json"}

    try:
        logger.info("Enviando e-mail via Google Apps Script para: %s", destinatario)
        resp = _post_with_retry(GOOGLE_SCRIPT_URL, payload, headers)
        if 200 <= resp.status_code < 300:
            try:
                data = resp.json()
                if data.get("status") == "success":
                    logger.info("E-mail enviado com sucesso via Google Apps Script para %s", destinatario)
                    return True
                logger.warning("Falha ao enviar via Google Script (Script reportou erro): %s", data.get("message"))
            except Exception:
                if "success" in resp.text.lower():
                    logger.info("E-mail enviado com sucesso via Google Apps Script (texto) para %s", destinatario)
                    return True
                logger.warning("Falha ao ler resposta do Google Script: %s", resp.text)
        else:
            logger.warning("Erro HTTP ao enviar via Google Script: %s - %s", resp.status_code, resp.text)
        return False
    except Exception as exc:
        logger.warning("Erro ao enviar e-mail via Google Script: %s", exc)
        return False


def enviar_email(destinatario: str, assunto: str, mensagem_html: str):
    """
    Envia e-mail pelo provedor configurado em EMAIL_PROVIDER.
    """
    html_final = _wrap_email_html(mensagem_html)
    providers = {
        "smtp": _send_via_smtp,
        "gmail": _send_via_gmail_api,
        "gmail_api": _send_via_gmail_api,
        "mailtrap": _send_via_mailtrap,
        "mailtrap_api": _send_via_mailtrap,
        "google_script": _send_via_google_script,
        "gmail_script": _send_via_google_script,
    }
    sender = providers.get(EMAIL_PROVIDER)
    if not sender:
        logger.warning(
            "EMAIL_PROVIDER invalido (%s). Use smtp, gmail_api, mailtrap ou google_script.",
            EMAIL_PROVIDER,
        )
        return False
    return sender(destinatario, assunto, html_final)
