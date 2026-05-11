# nogai.py - Módulo especializado em interações de texto automotivo usando Google Gemini (New SDK)
# backend/services/nogai.py
import logging
import os
import requests
import time
from dotenv import load_dotenv
from google import genai
from google.genai import types
import json
from functools import lru_cache

load_dotenv()

logger = logging.getLogger(__name__)

HTTP_TIMEOUT = (3.05, 8)
FIPE_BASE_URL = "https://parallelum.com.br/fipe/api/v1"
FIPE_CACHE_TTL_SECONDS = max(60, int(os.getenv("FIPE_CACHE_TTL_SECONDS", "86400")))

SYSTEM_PROMPT = """
Você é o NOG, um consultor automotivo profissional e mentor didático com ampla experiência no mercado brasileiro. 
Sua missão é traduzir o "mecaniquês" para uma linguagem que qualquer pessoa, mesmo leiga, consiga entender com clareza.

- Sempre que você receber um "oi" ou "olá", responda com "Olá! Sou o NOG, seu Consultor Automotivo Inteligente. Estou aqui ajudar com suas dúvidas sobre automóveis. Como posso ajudar hoje? 🚗✨"

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
- Caso o assunto não for sobre automóveis ou peças de automóveis, responda: "Desculpe, mas só posso ajudar com assuntos relacionados a automóveis."

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

@lru_cache(maxsize=512)
def _cached_fipe_json(url: str, cache_bucket: int):
    response = requests.get(url, timeout=HTTP_TIMEOUT)
    response.raise_for_status()
    return response.json()


def _get_fipe_json(path: str):
    cache_bucket = int(time.time() // FIPE_CACHE_TTL_SECONDS)
    url = f"{FIPE_BASE_URL}/{path.lstrip('/')}"
    return _cached_fipe_json(url, cache_bucket)


def get_fipe_value(tipo, marca_nome, modelo_nome, ano):
    """Busca o valor medio de mercado via API FIPE com cache curto."""
    tipo_norm = str(tipo or "").lower()
    if tipo_norm == "carro":
        tipo_norm = "carros"
    elif tipo_norm == "moto":
        tipo_norm = "motos"
    elif tipo_norm == "caminhao":
        tipo_norm = "caminhoes"
    if tipo_norm not in {"carros", "motos", "caminhoes"}:
        return None

    marca_query = str(marca_nome or "").strip().lower()
    modelo_query = str(modelo_nome or "").strip().lower()
    ano_query = str(ano or "").strip()
    if not marca_query or not modelo_query or not ano_query:
        return None

    try:
        marcas = _get_fipe_json(f"{tipo_norm}/marcas")
        marca_obj = next((m for m in marcas if marca_query in m["nome"].lower()), None)
        if not marca_obj:
            return None

        modelos_resp = _get_fipe_json(f"{tipo_norm}/marcas/{marca_obj['codigo']}/modelos")
        candidatos = [m for m in modelos_resp.get("modelos", []) if modelo_query in m["nome"].lower()]
        if not candidatos:
            return None

        for modelo in candidatos:
            anos_disponiveis = _get_fipe_json(
                f"{tipo_norm}/marcas/{marca_obj['codigo']}/modelos/{modelo['codigo']}/anos"
            )
            ano_obj = next((a for a in anos_disponiveis if a["nome"].startswith(ano_query)), None)
            if ano_obj:
                return _get_fipe_json(
                    f"{tipo_norm}/marcas/{marca_obj['codigo']}/modelos/{modelo['codigo']}/anos/{ano_obj['codigo']}"
                )
        return None
    except Exception as e:
        logger.error(f"Erro ao buscar FIPE: {e}")
        return None

from routes.database import get_mysql_history

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
MODELS_TO_TRY = ["gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-flash-latest"]


def _is_retryable_model_error(error: Exception) -> bool:
    error_str = str(error)
    return (
        "503" in error_str
        or "UNAVAILABLE" in error_str
        or "high demand" in error_str.lower()
    )


def _generate_content_with_fallback(
    *,
    contents,
    config=None,
    primary_model="gemini-2.5-flash",
    log_context="Gemini",
):
    try:
        return client.models.generate_content(
            model=primary_model,
            config=config,
            contents=contents,
        )
    except Exception as e:
        if not _is_retryable_model_error(e):
            raise e

        logger.warning("%s indisponivel. Tentando modelos de fallback...", log_context)
        for model_name in MODELS_TO_TRY:
            try:
                return client.models.generate_content(
                    model=model_name,
                    config=config,
                    contents=contents,
                )
            except Exception as fallback_err:
                logger.error("Fallback para %s (%s) falhou: %s", model_name, log_context, fallback_err)
                continue
        raise e


def gerar_resposta(mensagem: str, user_id: int, user_data: dict = None, historico: list | None = None) -> str:
    try:
        logger.info(f"NOG Gemini: Processando msg do usuário {user_id}")
        
        historico_mysql = historico if historico is not None else get_mysql_history(user_id)
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

def _clean_search_term(value):
    if value is None:
        return None
    term = str(value).strip().replace('"', '').replace("'", "")
    if not term or term.upper() == "NONE":
        return None
    return term[:120]


def gerar_termos_busca(mensagem: str, historico: list = None) -> dict:
    """
    Extrai, em uma unica chamada ao Gemini, os termos de busca usados para
    videos, compra de veiculos e compra de pecas.
    """
    try:
        contexto_historico = ""
        if historico:
            resumo = "\n".join([
                f"{'Usuario' if m['role'] == 'user' else 'IA'}: {m['content']}"
                for m in historico[-3:]
            ])
            contexto_historico = f"\nHistorico recente:\n{resumo}\n"

        prompt = f"""
        Voce extrai termos curtos de busca a partir de conversas automotivas.

        {contexto_historico}

        Mensagem atual do usuario: "{mensagem}"

        Regras:
        - youtube: termo especifico para tutorial no YouTube se houver ajuda tecnica automotiva; senao null.
        - loja: termo de veiculo se o usuario quer comprar, comparar modelos ou ver precos; senao null.
        - pecas: termo de peca/acessorio automotivo se houver intencao de comprar ou pesquisar peca; senao null.
        - Use termos em portugues, curtos e seguros para URL.
        - Nao invente termos para conversa generica como oi, obrigado ou assunto fora de automoveis.

        Retorne APENAS JSON valido neste formato:
        {{"youtube": string|null, "loja": string|null, "pecas": string|null}}
        """

        response = _generate_content_with_fallback(
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json"),
            log_context="Extracao de termos",
        )
        data = json.loads(response.text)
        return {
            "youtube": _clean_search_term(data.get("youtube")),
            "loja": _clean_search_term(data.get("loja")),
            "pecas": _clean_search_term(data.get("pecas")),
        }
    except Exception as e:
        logger.error(f"Erro ao gerar termos de busca consolidados: {e}")
        return {"youtube": None, "loja": None, "pecas": None}


def gerar_termo_busca_youtube(mensagem: str, historico: list = None) -> str | None:
    """
    Avalia a mensagem do usuário e o histórico para decidir se 
    há necessidade de recomendar um vídeo de tutorial.
    Retorna uma string curta para pesquisa no YouTube ou None.
    """
    try:
        contexto_historico = ""
        if historico:
            # Pega as últimas 3 interações para contexto
            resumo = "\n".join([f"{'Usuário' if m['role']=='user' else 'IA'}: {m['content']}" for m in historico[-3:]])
            contexto_historico = f"\nHistórico recente da conversa:\n{resumo}\n"

        prompt = f"""
        Você é um assistente que extrai termos de pesquisa do YouTube focados EXCLUSIVAMENTE em mecânica automotiva.
        Analise a mensagem do usuário e o histórico da conversa abaixo.
        
        {contexto_historico}
        
        Mensagem atual do Usuário: "{mensagem}"
        
        Sua tarefa:
        1. Se a mensagem pedir ajuda técnica, gere UM termo de pesquisa específico.
        2. Se o assunto for recorrente, gere um termo MAIS ESPECÍFICO ou uma variação (ex: em vez de apenas "óleo", use "viscosidade óleo motor" ou "melhores marcas óleo").
        3. O termo DEVE incluir palavras de contexto como "carro", "motor", "mecânica" ou o modelo do veículo.
        4. Se for apenas conversa genérica (oi, obrigado), retorne APENAS a palavra NONE.
        
        Retorne APENAS o termo de pesquisa ou NONE. Sem aspas ou explicações.
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

def gerar_termo_busca_loja(mensagem: str, historico: list = None) -> str | None:
    """
    Avalia a mensagem e o histórico para sugerir links de compra de veículos.
    """
    try:
        contexto_historico = ""
        if historico:
            resumo = "\n".join([f"{m['role']}: {m['content']}" for m in historico[-2:]])
            contexto_historico = f"\nContexto anterior:\n{resumo}\n"

        prompt = f"""
        Você é um especialista em mercado automotivo.
        Analise se o usuário quer comprar um veículo, sugerir modelos ou ver preços.
        
        {contexto_historico}
        
        Mensagem atual: "{mensagem}"
        
        Gere UM termo de busca curto e variado. Se ele já perguntou de um carro, tente sugerir um comparativo ou versão específica.
        Se não for sobre compra, retorne APENAS: NONE.
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

def gerar_termo_busca_pecas(mensagem: str, historico: list = None) -> str | None:
    """
    Avalia a mensagem e o histórico para sugerir compra de peças.
    """
    try:
        contexto_historico = ""
        if historico:
            resumo = "\n".join([f"{m['role']}: {m['content']}" for m in historico[-2:]])
            contexto_historico = f"\nContexto anterior:\n{resumo}\n"

        prompt = f"""
        Extraia UM termo de busca de PEÇAS automotivas.
        
        {contexto_historico}
        
        Mensagem atual: "{mensagem}"
        
        Se o usuário já perguntou de uma peça, gere um termo para uma marca específica ou componente relacionado.
        Se não for sobre peças, retorne APENAS: NONE.
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

def prever_intervalo_manutencao(descricao: str, veiculo_info: str = "") -> dict:
    """
    Usa IA para prever o intervalo de manutenção (dias e km) com base na descrição.
    Retorna um dicionário com 'intervalo_dias' e 'intervalo_km'.
    """
    try:
        prompt = f"""
        Você é um especialista em manutenção automotiva.
        Analise a seguinte descrição de um serviço realizado e preveja quando deve ser o próximo retorno (intervalo em dias e quilometragem).
        
        Considere as melhores práticas do mercado brasileiro.
        Se a descrição não der pistas suficientes, use padrões comuns para o tipo de serviço detectado.
        
        Descrição: "{descricao}"
        {f"Veículo: {veiculo_info}" if veiculo_info else ""}
        
        Retorne APENAS um JSON no formato:
        {{
          "intervalo_dias": int ou null,
          "intervalo_km": int ou null,
          "justificativa": "breve explicação"
        }}
        """
        
        try:
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                ),
                contents=prompt
            )
            return json.loads(response.text)
        except Exception as e:
            logger.warning(f"Falha na previsão de intervalo com Gemini 2.0: {e}")
            # Fallback se o 2.0 falhar
            response = client.models.generate_content(
                model="gemini-2.0-flash-lite",
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                ),
                contents=prompt
            )
            return json.loads(response.text)
            
    except Exception as e:
        logger.error(f"Erro ao prever intervalo com IA: {e}")
        return {"intervalo_dias": None, "intervalo_km": None, "justificativa": "Falha na análise"}
