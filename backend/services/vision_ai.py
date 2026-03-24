# vision_ai.py - Módulo de análise visual usando Google Gemini API (New SDK)
import os
import base64
import logging
import time
from dotenv import load_dotenv
from google import genai
from google.genai import types
from PIL import Image
import io

load_dotenv()

logger = logging.getLogger(__name__)

VISION_PROMPT = """
Você é o NOG, especialista em inspeção veicular técnica ("Raio-X Mecânico").
Analise a imagem buscando falhas ocultas e detalhes de mercado.

Sua Resposta deve conter:
1. 📋 Resumo do Estado (Lataria, Pneus, Detalhes).
2. 🔧 Alerta Mecânico (aponte possíveis problemas invisíveis comuns a este modelo).
Indique se vê ferrugem, desalinhamentos ou vazamentos.
3. 💰 Estimativa de Valor (Veredito: Bom estado, Cuidado ou Bomba).

Seja didático, use negrito para termos técnicos e emojis. Proteja o comprador.
"""

# Ordem de preferência dos modelos
MODELS_TO_TRY = ["gemini-2.0-flash", "gemini-1.5-flash"]
client = genai.Client(api_key=os.getenv("API_GEMINI"))

def analisar_imagem(image_b64: str, pergunta: str | None = None) -> str:
    try:
        logger.info(f"👁️ Gemini Vision (New SDK): Analisando imagem...")
        
        # 1. Decodificar Base64 para Imagem PIL
        if "," in image_b64:
            image_b64 = image_b64.split(",")[1]
        
        image_data = base64.b64decode(image_b64)
        img = Image.open(io.BytesIO(image_data))

        # 2. Preparar Prompt
        prompt = VISION_PROMPT
        if pergunta:
            prompt += f"\n\nPergunta específica do usuário: {pergunta}"

        # 3. Gerar conteúdo multimodal usando o novo SDK com Fallback
        try:
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=[prompt, img]
            )
            logger.info(f"✓ Análise visual completa (Gemini 2.5 Flash)")
            return response.text
        except Exception as e:
            error_str = str(e)
            if "503" in error_str or "UNAVAILABLE" in error_str or "high demand" in error_str.lower():
                logger.warning(f"⚠️ Gemini Vision 2.5 Flash indisponível (503). Tentando modelos estáveis...")
                time.sleep(1)
                
                for model_name in MODELS_TO_TRY:
                    try:
                        logger.info(f"Tentando fallback para {model_name} (Vision)...")
                        response = client.models.generate_content(
                            model=model_name,
                            contents=[prompt, img]
                        )
                        logger.info(f"✓ Análise visual completa ({model_name})")
                        return response.text
                    except Exception as fallback_err:
                        logger.error(f"❌ Fallback para {model_name} (Vision) falhou: {fallback_err}")
                        continue
            
            # Se não for 503 ou todos falharem
            raise e

    except Exception as e:
        logger.error(f"❌ Erro na análise de visão Gemini (New SDK): {e}", exc_info=True)
        return "❌ O NOG não conseguiu analisar esta imagem via satélite no momento."