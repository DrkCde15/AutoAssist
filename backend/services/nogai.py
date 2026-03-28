# nogai.py - Módulo especializado em interações de texto automotivo usando Google Gemini (New SDK)
# backend/services/nogai.py
import logging
import os
import pymysql
from pymysql.cursors import DictCursor
import requests
import time
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """
Você é o NOG, um consultor automotivo profissional e mentor didático com ampla experiência no mercado brasileiro. 
Sua missão é traduzir o "mecaniquês" para uma linguagem que qualquer pessoa, mesmo leiga, consiga entender com clareza.

- Sempre que você receber um "oi" ou "olá", responda com "Olá! Sou o NOG, seu Consultor Automotivo Inteligente. Estou aqui para traduzir o mundo dos carros para você. Como posso ajudar hoje? 🚗✨"

Diretrizes de Personalidade & Didática:
- **Mecânico Mentor**: Você é experiente e técnico, mas explica tudo como um professor paciente para quem não entende nada de carros.
- **Tradução de Termos**: Sempre que usar um termo técnico (como "junta do cabeçote", "homocinética" ou "estequiometria"), explique brevemente o que é de forma simples ou use uma analogia.
- **Uso de Analogias**: Compare peças do carro com coisas do dia a dia (Ex: "Os freios são como os pneus de um tênis de corrida...").
- **Cético e Protetor**: Continue protegendo o usuário de gastos desnecessários ou riscos de segurança, explicando o "porquê" de forma didática.

Regras de Formatação (Obrigatório):
- Use **Negrito** para termos técnicos, peças, diagnósticos e valores.
- Use > Citações para alertas de segurança ou avisos importantes.
- Use Listas pontuadas (•) para listar sintomas ou passos de verificação.
- Use Títulos (Ex: ### 💡 Entendendo o Problema) para organizar a explicação.
- Deixe uma linha em branco entre cada parágrafo para facilitar a leitura.
- Use bastante Emojis para manter o tom amigável (🔧, 🚗, ⚠️, 💡).

Estrutura de Resposta Padrão:
1. 🏁 **Resumo Direto**: Uma explicação simples do que está acontecendo.
2. 📖 **Dicionário do NOG**: Se houver peças complexas, explique o que elas fazem aqui.
3. 🔧 **Passo a Passo**: O que o usuário deve fazer ou verificar, ou como falar com o mecânico.
4. 💰 **Valores e FIPE**: Estimativas de custo e referências de mercado, sempre explicando o que influencia o preço.
"""

PREMIUM_TUTORIAL_PROMPT = """
[DIRETRIZ PREMIUM EXCLUSIVA PARA ESTE USUÁRIO]:
- **VÍDEOS TUTORIAIS**: O sistema em anexo vai capturar vídeos automaticamente abaixo da sua resposta. JAMAIS diga que você "não consegue mostrar vídeos por ser uma IA de texto". Se o usuário pedir um vídeo sobre o assunto, confirme educadamente: "Claro! Aqui estão alguns vídeos que encontrei para te ajudar com isso:" e termine o aviso, prosseguindo com dicas em texto.
"""

def get_fipe_value(tipo, marca_nome, modelo_nome, ano):
    """Busca o valor médio de mercado via API externa FIPE (Parallelum)."""
    BASE_URL = "https://parallelum.com.br/fipe/api/v1"
    try:
        response = requests.get(f"{BASE_URL}/{tipo}/marcas", timeout=10)
        if response.status_code != 200: return None
        marcas = response.json()
        marca_obj = next((m for m in marcas if marca_nome.lower() in m["nome"].lower()), None)
        if not marca_obj: return None
        response = requests.get(f"{BASE_URL}/{tipo}/marcas/{marca_obj['codigo']}/modelos", timeout=10)
        if response.status_code != 200: return None
        modelos_resp = response.json()
        candidatos = [m for m in modelos_resp.get("modelos", []) if modelo_nome.lower() in m["nome"].lower()]
        if not candidatos: return None
        for modelo in candidatos:
            response = requests.get(f"{BASE_URL}/{tipo}/marcas/{marca_obj['codigo']}/modelos/{modelo['codigo']}/anos", timeout=10)
            if response.status_code != 200: continue
            anos_disponiveis = response.json()
            ano_obj = next((a for a in anos_disponiveis if a["nome"].startswith(str(ano))), None)
            if ano_obj:
                valor_resp = requests.get(f"{BASE_URL}/{tipo}/marcas/{marca_obj['codigo']}/modelos/{modelo['codigo']}/anos/{ano_obj['codigo']}", timeout=10)
                if valor_resp.status_code == 200: return valor_resp.json()
        return None
    except Exception as e:
        logger.error(f"Erro ao buscar FIPE: {e}")
        return None

def get_mysql_history(user_id: int, limit: int = 5):
    """Recupera o histórico do MySQL."""
    try:
        conn = pymysql.connect(
            host=os.getenv('DB_HOST'),
            port=int(os.getenv('DB_PORT', 3306)),
            user=os.getenv('DB_USER'),
            password=os.getenv('DB_PASSWORD'),
            database=os.getenv('DB_NAME'),
            cursorclass=DictCursor
        )
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT mensagem_usuario, resposta_ia FROM chats WHERE user_id = %s ORDER BY created_at DESC LIMIT %s",
                (user_id, limit)
            )
            rows = cursor.fetchall()
            history = []
            for row in reversed(rows):
                if row['mensagem_usuario']:
                    history.append({"role": "user", "content": row['mensagem_usuario']})
                if row['resposta_ia']:
                    history.append({"role": "model", "content": row['resposta_ia']})
            return history
    except Exception as e:
        logger.error(f"Erro histórico MySQL: {e}")
        return []
    finally:
        if 'conn' in locals(): conn.close()

# Inicializa o cliente Gemini (Deixando o SDK escolher a melhor versão estável)
client = genai.Client(api_key=os.getenv("API_GEMINI"))

def transformar_historico_gemini(historico_mysql):
    """Converte o histórico do MySQL para o formato do novo SDK."""
    gemini_history = []
    for msg in historico_mysql:
        # No novo SDK, o assistente é 'model'
        role = "user" if msg["role"] == "user" else "model"
        gemini_history.append(types.Content(
            role=role,
            parts=[types.Part.from_text(text=msg["content"])]
        ))
    return gemini_history

# Ordem de preferência dos modelos
MODELS_TO_TRY = ["gemini-2.0-flash", "gemini-1.5-flash"]

def gerar_resposta(mensagem: str, user_id: int, user_data: dict = None) -> str:
    try:
        logger.info(f"NOG Gemini: Processando msg do usuário {user_id}")
        
        historico_mysql = get_mysql_history(user_id)
        historico_gemini = transformar_historico_gemini(historico_mysql)
        
        prompt_instrucoes = SYSTEM_PROMPT
        if user_data and user_data.get("is_premium"):
            prompt_instrucoes += PREMIUM_TUTORIAL_PROMPT
            
        prompt_final = mensagem
        if user_data and (user_data.get("possui_veiculo") or user_data.get("lista_veiculos")):
            veiculos = user_data.get("lista_veiculos")
            if veiculos:
                lista_str = "; ".join([f"{v.get('tipo', 'veículo')} {v.get('marca', '')} {v.get('modelo', '')} ano {v.get('ano_fabricacao', '')}".strip() for v in veiculos])
                contexto_veiculo = f"\n\n[CONTEXTO DO USUÁRIO]: O usuário possui os seguintes veículos cadastrados: {lista_str}. Responda considerando os veículos do usuário se for relevante."
            else:
                contexto_veiculo = (f"\n\n[CONTEXTO DO USUÁRIO]: O usuário possui um(a) {user_data.get('veiculo_tipo')} "
                                    f"{user_data.get('veiculo_marca')} {user_data.get('veiculo_modelo')} "
                                    f"ano {user_data.get('veiculo_ano_fabricacao')}. "
                                    f"Responda considerando este veículo se for relevante.")
            prompt_final = contexto_veiculo + "\n\nPergunta do usuário: " + mensagem
            
        # Tentativa inicial com Gemini 2.5 Flash
        try:
            chat = client.chats.create(
                model="gemini-2.5-flash",
                config=types.GenerateContentConfig(
                    system_instruction=prompt_instrucoes,
                    temperature=0.7,
                ),
                history=historico_gemini
            )
            response = chat.send_message(message=prompt_final)
            return response.text
        except Exception as e:
            error_str = str(e)
            if "503" in error_str or "UNAVAILABLE" in error_str or "high demand" in error_str.lower():
                logger.warning(f"⚠️ Gemini 2.5 Flash indisponível (503). Tentando modelos estáveis...")
                time.sleep(1) # Pequeno atraso antes do fallback
                
                for model_name in MODELS_TO_TRY:
                    try:
                        logger.info(f"Tentando fallback para {model_name}...")
                        chat = client.chats.create(
                            model=model_name,
                            config=types.GenerateContentConfig(
                                system_instruction=prompt_instrucoes,
                                temperature=0.7,
                            ),
                            history=historico_gemini
                        )
                        response = chat.send_message(message=prompt_final)
                        return response.text
                    except Exception as fallback_err:
                        logger.error(f"❌ Fallback para {model_name} também falhou: {fallback_err}")
                        continue
            
            # Se não for erro 503 ou todos fallbacks falharem
            raise e
        
    except Exception as e:
        logger.error(f"❌ Erro no NOG (Gemini New SDK): {e}", exc_info=True)
        return "❌ Erro ao conectar com a inteligência na nuvem."

def gerar_termo_busca_youtube(mensagem: str, resposta_ia: str = "") -> str | None:
    """
    Avalia a mensagem do usuário e opcionalmente a resposta da IA para decidir se 
    há necessidade de recomendar um vídeo de tutorial ou explicação automotiva.
    Retorna uma string curta para pesquisa no YouTube ou None.
    """
    try:
        prompt = f"""
        Você é um assistente que extrai termos de pesquisa do YouTube.
        Analise a seguinte mensagem do usuário solicitando ajuda automotiva.
        Se a mensagem pedir como consertar, trocar, verificar, identificar ou entender alguma peça ou problema no carro, gere UM termo de busca curto, direto e otimizado para o YouTube.
        Exemplo: "como trocar pneu celta", "barulho suspensão gol G4", "o que é homocinética".
        Se for apenas uma saudação, agradecimento ou conversa genérica ("oi", "obrigado", "tchau", "bom dia"), retorne APENAS a palavra NONE.
        Retorne APENAS o termo de pesquisa ou NONE. Não adicione aspas, pontos finais ou explicações.
        
        Mensagem do Usuário: "{mensagem}"
        """
        
        # Tentativa inicial com Gemini 2.5 Flash
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
            )
        except Exception as e:
            error_str = str(e)
            if "503" in error_str or "UNAVAILABLE" in error_str or "high demand" in error_str.lower():
                logger.warning(f"⚠️ YouTube Search LLM indisponível (503). Tentando modelos estáveis...")
                
                response = None
                for model_name in MODELS_TO_TRY:
                    try:
                        logger.info(f"Tentando fallback para {model_name} (YouTube Search)...")
                        response = client.models.generate_content(
                            model=model_name,
                            contents=prompt,
                        )
                        if response: break
                    except Exception as fallback_err:
                        logger.error(f"❌ Fallback para {model_name} (YouTube) falhou: {fallback_err}")
                        continue
                
                if not response: raise e
            else:
                raise e
        
        termo = response.text.strip().replace('"', '').replace("'", "")
        if termo.upper() == "NONE" or not termo:
            return None
            
        logger.info(f"Termo de busca YouTube extraído: {termo}")
        return termo
        
    except Exception as e:
        logger.error(f"❌ Erro ao gerar termo de busca YouTube: {e}")
        return None

def gerar_termo_busca_loja(mensagem: str) -> str | None:
    """
    Avalia a mensagem do usuário para decidir se há necessidade de recomendar 
    links de lojas para comprar um veículo.
    Retorna uma string curta para pesquisa ou None.
    """
    try:
        prompt = f"""
        Você é um assistente que extrai termos de pesquisa de veículos.
        Analise a seguinte mensagem do usuário.
        Se a mensagem indicar que o usuário quer comprar um veículo (carro, moto, caminhão, etc.), sugerir modelos, perguntar o preço ou onde comprar, gere UM termo de busca curto focado no modelo ou busca.
        Exemplo: "Honda Civic", "Yamaha MT-09", "Volvo FH", "comprar moto".
        Se não envolver compra de veículo, retorne APENAS a palavra NONE.
        Retorne APENAS o termo de pesquisa ou NONE. Não adicione aspas.
        
        Mensagem do Usuário: "{mensagem}"
        """
        try:
            response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
        except Exception as e:
            error_str = str(e)
            if "503" in error_str or "UNAVAILABLE" in error_str or "high demand" in error_str.lower():
                response = None
                for model_name in MODELS_TO_TRY:
                    try:
                        response = client.models.generate_content(model=model_name, contents=prompt)
                        if response: break
                    except:
                        continue
                if not response: raise e
            else:
                raise e
        
        termo = response.text.strip().replace('"', '').replace("'", "")
        if termo.upper() == "NONE" or not termo:
            return None
        return termo
    except Exception as e:
        logger.error(f"Erro ao gerar termo busca loja: {e}")
        return None

def gerar_termo_busca_pecas(mensagem: str) -> str | None:
    """
    Avalia a mensagem do usuário para decidir se há necessidade de recomendar 
    links para comprar peças e componentes automotivos.
    Retorna uma string curta para pesquisa ou None.
    """
    try:
        prompt = f"""
        Você é um assistente que extrai termos de pesquisa de PEÇAS automotivas.
        Analise a seguinte mensagem do usuário.
        Se a mensagem indicar que o usuário quer comprar uma peça (ex: pneu, bateria, óleo, pastilha de freio, amortecedor, etc.), gere UM termo de busca curto focado na peça e no modelo do carro (se mencionado).
        Exemplo: "pneu aro 15", "bateria Moura", "pastilha de freio Honda Civic", "óleo de motor 5w30".
        Se não envolver compra de peças, retorne APENAS a palavra NONE.
        Retorne APENAS o termo de pesquisa ou NONE. Não adicione aspas.
        
        Mensagem do Usuário: "{mensagem}"
        """
        try:
            response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
        except Exception as e:
            error_str = str(e)
            if "503" in error_str or "UNAVAILABLE" in error_str or "high demand" in error_str.lower():
                response = None
                for model_name in MODELS_TO_TRY:
                    try:
                        response = client.models.generate_content(model=model_name, contents=prompt)
                        if response: break
                    except:
                        continue
                if not response: raise e
            else:
                raise e
        
        termo = response.text.strip().replace('"', '').replace("'", "")
        if termo.upper() == "NONE" or not termo:
            return None
        return termo
    except Exception as e:
        logger.error(f"Erro ao gerar termo busca pecas: {e}")
        return None