import os
import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests
from dotenv import load_dotenv

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

RESEND_API_KEY = (os.getenv("RESEND_API_KEY") or "").strip()
BREVO_API_KEY = (os.getenv("BREVO_API_KEY") or "").strip()
SENDGRID_API_KEY = (os.getenv("SENDGRID_API_KEY") or "").strip()
WEBHOOK_EMAIL_URL = (os.getenv("WEBHOOK_EMAIL_URL") or "").strip()
WEBHOOK_EMAIL_SECRET = (os.getenv("WEBHOOK_EMAIL_SECRET") or "").strip()


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


def _send_via_resend(destinatario: str, assunto: str, html_final: str) -> bool:
    if not RESEND_API_KEY or not EMAIL_FROM:
        return False

    payload = {
        "from": _from_string(),
        "to": [destinatario],
        "subject": assunto,
        "html": html_final,
    }
    headers = {
        "Authorization": f"Bearer {RESEND_API_KEY}",
        "Content-Type": "application/json",
    }
    resp = _post_with_retry("https://api.resend.com/emails", payload, headers)
    if 200 <= resp.status_code < 300:
        return True
    print(f"Erro ao enviar e-mail via Resend: HTTP {resp.status_code} - {resp.text}")
    return False


def _send_via_brevo(destinatario: str, assunto: str, html_final: str) -> bool:
    if not BREVO_API_KEY or not EMAIL_FROM:
        return False

    payload = {
        "sender": {"name": EMAIL_FROM_NAME or "AutoAssist", "email": EMAIL_FROM},
        "to": [{"email": destinatario}],
        "subject": assunto,
        "htmlContent": html_final,
    }
    headers = {
        "api-key": BREVO_API_KEY,
        "Content-Type": "application/json",
    }
    resp = _post_with_retry("https://api.brevo.com/v3/smtp/email", payload, headers)
    if 200 <= resp.status_code < 300:
        return True
    print(f"Erro ao enviar e-mail via Brevo: HTTP {resp.status_code} - {resp.text}")
    return False


def _send_via_sendgrid(destinatario: str, assunto: str, html_final: str) -> bool:
    if not SENDGRID_API_KEY or not EMAIL_FROM:
        return False

    payload = {
        "personalizations": [{"to": [{"email": destinatario}]}],
        "from": {"email": EMAIL_FROM, "name": EMAIL_FROM_NAME or "AutoAssist"},
        "subject": assunto,
        "content": [{"type": "text/html", "value": html_final}],
    }
    headers = {
        "Authorization": f"Bearer {SENDGRID_API_KEY}",
        "Content-Type": "application/json",
    }
    resp = _post_with_retry("https://api.sendgrid.com/v3/mail/send", payload, headers)
    if 200 <= resp.status_code < 300:
        return True
    print(f"Erro ao enviar e-mail via SendGrid: HTTP {resp.status_code} - {resp.text}")
    return False


def _send_via_webhook(destinatario: str, assunto: str, html_final: str) -> bool:
    if not WEBHOOK_EMAIL_URL:
        return False

    payload = {
        "to": destinatario,
        "subject": assunto,
        "html": html_final,
        "from": _from_string(),
        "from_name": EMAIL_FROM_NAME or "AutoAssist",
    }
    headers = {"Content-Type": "application/json"}
    if WEBHOOK_EMAIL_SECRET:
        headers["X-Webhook-Secret"] = WEBHOOK_EMAIL_SECRET

    resp = _post_with_retry(WEBHOOK_EMAIL_URL, payload, headers)
    if 200 <= resp.status_code < 300:
        return True
    print(f"Erro ao enviar e-mail via Webhook: HTTP {resp.status_code} - {resp.text}")
    return False


def _send_via_smtp(destinatario: str, assunto: str, html_final: str) -> bool:
    if not EMAIL_REMETENTE or not EMAIL_SENHA_APP:
        return False

    msg = MIMEMultipart()
    msg["From"] = _from_string() or EMAIL_REMETENTE
    msg["To"] = destinatario
    msg["Subject"] = assunto
    msg.attach(MIMEText(html_final, "html"))

    try:
        print(f"--- Tentando enviar email SMTP para: {destinatario} ---")
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=SMTP_TIMEOUT_SECONDS) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(EMAIL_REMETENTE, EMAIL_SENHA_APP)
            server.send_message(msg)
        return True
    except Exception as exc:
        print(f"Erro ao enviar e-mail via SMTP: {exc}")
        return False


def enviar_email(destinatario: str, assunto: str, mensagem_html: str):
    """
    Envia e-mail somente via SMTP.
    """
    html_final = _wrap_email_html(mensagem_html)
    if EMAIL_PROVIDER != "smtp":
        print("EMAIL_PROVIDER diferente de smtp foi ignorado; envio usando SMTP apenas.")
    return _send_via_smtp(destinatario, assunto, html_final)
