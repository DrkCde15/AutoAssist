import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

# Carrega variáveis de ambiente
basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '..', '.env'))

EMAIL_REMETENTE = os.getenv("EMAIL_REMETENTE")
EMAIL_SENHA_APP = os.getenv("EMAIL_SENHA_APP")

def enviar_email(destinatario: str, assunto: str, mensagem_html: str):
    """
    Envia um e-mail utilizando SMTP (Gmail) com o layout premium do AutoAssist.
    """
    try:
        # Template base premium (Mantido do padrão anterior)
        template = """
        <div style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; padding: 30px; background-color: #f3f4f6; min-height: 100%;">
            <div style="max-width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 16px; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);">
                <!-- Header -->
                <div style="background: linear-gradient(135deg, #2563eb, #1d4ed8); padding: 30px; text-align: center;">
                    <h1 style="color: #ffffff; margin: 0; font-size: 24px; letter-spacing: 1px;">AutoAssist</h1>
                </div>
                
                <!-- Content -->
                <div style="padding: 40px 30px; line-height: 1.6; color: #374151;">
                    {{CONTENT}}
                </div>
                
                <!-- Footer -->
                <div style="padding: 20px; background-color: #f9fafb; text-align: center; border-top: 1px solid #e5e7eb;">
                    <p style="margin: 0; font-size: 12px; color: #9ca3af;">
                        &copy; 2026 AutoAssist - Seu assistente automotivo inteligente.<br>
                        Este é um e-mail automático, por favor não responda.
                    </p>
                </div>
            </div>
        </div>
        """
        
        html_final = template.replace("{{CONTENT}}", mensagem_html)

        # Configuração da Mensagem MIME
        msg = MIMEMultipart()
        msg['From'] = f"AutoAssist <{EMAIL_REMETENTE}>"
        msg['To'] = destinatario
        msg['Subject'] = assunto
        msg.attach(MIMEText(html_final, 'html'))

        # Envio via SMTP Gmail
        print(f"--- Tentando enviar email via SMTP para: {destinatario} ---")
        
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(EMAIL_REMETENTE, EMAIL_SENHA_APP)
            server.send_message(msg)
            
        print(f"✅ E-mail enviado com sucesso via SMTP!")
        return True
    except Exception as e:
        print(f"❌ Erro ao enviar e-mail via SMTP: {e}")
        return False
