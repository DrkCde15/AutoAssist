import os
import smtplib
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
EMAIL_PROVIDER = (os.getenv("EMAIL_PROVIDER") or "auto").strip().lower()
SMTP_TIMEOUT_SECONDS = int(os.getenv("SMTP_TIMEOUT_SECONDS", "8"))
EMAIL_API_TIMEOUT_SECONDS = int(os.getenv("EMAIL_API_TIMEOUT_SECONDS", "8"))

RESEND_API_KEY = (os.getenv("RESEND_API_KEY") or "").strip()
BREVO_API_KEY = (os.getenv("BREVO_API_KEY") or "").strip()
SENDGRID_API_KEY = (os.getenv("SENDGRID_API_KEY") or "").strip()


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
    resp = requests.post(
        "https://api.resend.com/emails",
        json=payload,
        headers=headers,
        timeout=EMAIL_API_TIMEOUT_SECONDS,
    )
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
    resp = requests.post(
        "https://api.brevo.com/v3/smtp/email",
        json=payload,
        headers=headers,
        timeout=EMAIL_API_TIMEOUT_SECONDS,
    )
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
    resp = requests.post(
        "https://api.sendgrid.com/v3/mail/send",
        json=payload,
        headers=headers,
        timeout=EMAIL_API_TIMEOUT_SECONDS,
    )
    if 200 <= resp.status_code < 300:
        return True
    print(f"Erro ao enviar e-mail via SendGrid: HTTP {resp.status_code} - {resp.text}")
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
    Envia e-mail priorizando API HTTP (Render Free friendly) e usando SMTP como fallback.
    """
    html_final = _wrap_email_html(mensagem_html)
    provider_order = []

    if EMAIL_PROVIDER in ("resend", "brevo", "sendgrid", "smtp"):
        provider_order = [EMAIL_PROVIDER]
    else:
        provider_order = ["resend", "brevo", "sendgrid", "smtp"]

    for provider in provider_order:
        try:
            if provider == "resend" and _send_via_resend(destinatario, assunto, html_final):
                return True
            if provider == "brevo" and _send_via_brevo(destinatario, assunto, html_final):
                return True
            if provider == "sendgrid" and _send_via_sendgrid(destinatario, assunto, html_final):
                return True
            if provider == "smtp" and _send_via_smtp(destinatario, assunto, html_final):
                return True
        except Exception as exc:
            print(f"Erro ao enviar e-mail via {provider}: {exc}")

    print("Falha ao enviar e-mail: nenhum provider conseguiu entregar.")
    return False
