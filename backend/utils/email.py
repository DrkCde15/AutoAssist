import os
import resend
from dotenv import load_dotenv

# Carrega variáveis de ambiente
basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '..', '.env'))

RESEND_API_KEY = os.getenv("RESEND_API_KEY")
EMAIL_REMETENTE = os.getenv("EMAIL_REMETENTE")

resend.api_key = RESEND_API_KEY

def enviar_email(destinatario: str, assunto: str, mensagem_html: str):
    """
    Envia um e-mail utilizando a API da Resend com um layout premium.
    """
    try:
        # Template base premium inspirado no Mintify
        html_final = f"""
        <div style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; padding: 30px; background-color: #f3f4f6; min-height: 100%;">
            <div style="max-width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 16px; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);">
                <!-- Header -->
                <div style="background: linear-gradient(135deg, #2563eb, #1d4ed8); padding: 30px; text-align: center;">
                    <h1 style="color: #ffffff; margin: 0; font-size: 24px; letter-spacing: 1px;">AutoAssist</h1>
                </div>
                
                <!-- Content -->
                <div style="padding: 40px 30px; line-height: 1.6; color: #374151;">
                    {mensagem_html}
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

        params = {
            "from": f"AutoAssist <{EMAIL_REMETENTE}>",
            "to": [destinatario],
            "subject": assunto,
            "html": html_final,
        }
        
        response = resend.Emails.send(params)
        print(f"✅ E-mail enviado com sucesso! ID: {response.get('id')}")
        return True
    except Exception as e:
        print(f"❌ Erro ao enviar e-mail via Resend: {e}")
        return False
