# vision_ai.py - Módulo especializado em análise visual automotiva
import os
import base64
import logging
import ollama
from neura_ai.core import Neura
from neura_ai.config import NeuraConfig

logger = logging.getLogger(__name__)

# Prompt especializado para o modelo de visão (moondream)
VISION_PROMPT = """
Você é um especialista em inspeção veicular técnica ("Raio-X Mecânico").
Analise a imagem buscando falhas ocultas e detalhes de mercado.
Identifique:
1. Veículo: Marca, modelo, ano/geração estimada.
2. Lataria/Estrutura: Desalinhamentos de peças (indicando batidas), ferrugem.
3. Mecânica Visível: Vazamentos, fumaça, estado dos pneus.
4. Acabamento: Faróis, vidros, interior.
5. Veredito: Bom estado, Cuidado (riscos médios) ou Bomba (riscos altos).
Seja extremamente crítico e técnico.
"""

# Força conexão local pura
host_escolhido = "http://127.0.0.1:11434"

try:
    # Tenta o modo v0.2.7 (Moondream para visão + Qwen 2 para texto)
    brain = Neura(model="gemma2:2b", vision_model="moondream:latest", system_prompt=VISION_PROMPT, host=host_escolhido)
except TypeError:
    # Fallback v0.2.5
    brain = Neura(model="gemma2:2b", vision_model="moondream:latest", system_prompt=VISION_PROMPT, host=host_escolhido)
    
    # RECONFIGURAÇÃO IMEDIATA
    brain.host = host_escolhido.rstrip('/')
    
    # Define os headers de bypass para o túnel
    bypass_headers = getattr(NeuraConfig, 'BYPASS_HEADERS', {"Bypass-Tunnel-Reminder": "true"})
    headers = bypass_headers if "loca.lt" in brain.host else {}
    
    # Sobrescreve o cliente do Ollama para parar de olhar para 127.0.0.1
    import ollama
    brain.client = ollama.Client(host=brain.host, headers=headers)
    logger.info(f"🚀 Host reconfigurado com sucesso para: {brain.host}")

def analisar_imagem(image_b64: str, pergunta: str | None = None, filename: str = "temp_vision_upload.png") -> str:
    
    temp_path = filename 
    
    try:
        # 1. Decodificar e salvar temporariamente
        if "," in image_b64:
            image_b64 = image_b64.split(",")[1]
        
        raw_data = base64.b64decode(image_b64)
        with open(temp_path, "wb") as f:
            f.write(raw_data)

        # 2. ESTÁGIO 1: VISÃO BRUTA (Moondream)
        logger.info(f"👁️ Estágio 1: Extraindo fatos da imagem via {brain.host}...")
        instrucao_visao = "Analyze this car for mechanical issues, rust, panel gaps, and estimated value condition."
        
        # O Core salva isso automaticamente na memória SQLite
        fatos_da_imagem = brain.get_response(instrucao_visao, image_path=temp_path)

        # 3. ESTÁGIO 2: INTERPRETAÇÃO DO NOG (Qwen)
        logger.info(f"🧠 Estágio 2: NOG interpretando resultados...")

        prompt_nog = f"""
        Você é o NOG, consultor automotivo expert.
        Com base na análise visual que você acabou de realizar (memória recente), responda:

        Pergunta do Cliente: {pergunta if pergunta else "O que você vê de relevante neste carro?"}

        Sua Resposta deve conter:
        1. 📋 Resumo do Estado (Lataria, Pneus, Detalhes).
        2. 🔧 Alerta Mecânico (aponte possíveis problemas invisíveis comuns a este modelo).
        3. 💰 Estimativa de Valor (Compare com a média de mercado/FIPE).

        Seja direto, proteja o comprador de ciladas.
        """

        # Chamada de texto puro (aproveitando o contexto da imagem salva no SQLite)
        resposta_final = brain.get_response(prompt_nog)
        
        logger.info(f"✓ Análise completa entregue pelo NOG")
        return resposta_final

    except Exception as e:
        logger.error(f"❌ Erro na análise de visão Neura: {e}", exc_info=True)
        return "❌ O NOG não conseguiu analisar esta imagem no momento."
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass