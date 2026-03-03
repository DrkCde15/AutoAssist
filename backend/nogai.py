# nogai.py - Módulo especializado em interações de texto automotivo usando Neura
import logging
import os
import ollama
import pymysql
from pymysql.cursors import DictCursor
import requests
from neura_ai.core import Neura # type: ignore
from neura_ai.config import NeuraConfig # type: ignore

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

def get_fipe_value(tipo, marca_nome, modelo_nome, ano):
    """
    Busca o valor médio de mercado via API externa FIPE (Parallelum).
    Implementação robusta que mapeia nomes de marcas e modelos para IDs da API.
    """
    BASE_URL = "https://parallelum.com.br/fipe/api/v1"
    
    try:
        # 1. Buscar e mapear Marca
        response = requests.get(f"{BASE_URL}/{tipo}/marcas", timeout=10)
        if response.status_code != 200:
            return None
        
        marcas = response.json()
        marca_obj = next(
            (m for m in marcas if marca_nome.lower() in m["nome"].lower()),
            None
        )
        if not marca_obj:
            return None

        # 2. Buscar Modelos da Marca
        response = requests.get(f"{BASE_URL}/{tipo}/marcas/{marca_obj['codigo']}/modelos", timeout=10)
        if response.status_code != 200:
            return None
            
        modelos_resp = response.json()
        # Filtra todos os modelos que batem com o nome (candidatos)
        candidatos = [m for m in modelos_resp.get("modelos", []) if modelo_nome.lower() in m["nome"].lower()]
        
        if not candidatos:
            return None

        # 3. Tentar encontrar o ano em cada variante do modelo
        for modelo in candidatos:
            response = requests.get(f"{BASE_URL}/{tipo}/marcas/{marca_obj['codigo']}/modelos/{modelo['codigo']}/anos", timeout=10)
            if response.status_code != 200:
                continue
                
            anos_disponiveis = response.json()
            ano_obj = next(
                (a for a in anos_disponiveis if a["nome"].startswith(str(ano))),
                None
            )
            
            if ano_obj:
                # 4. Se encontrou o ano, busca o valor final
                valor_resp = requests.get(
                    f"{BASE_URL}/{tipo}/marcas/{marca_obj['codigo']}/modelos/{modelo['codigo']}/anos/{ano_obj['codigo']}",
                    timeout=10
                )
                if valor_resp.status_code == 200:
                    return valor_resp.json()
        
        return None

    except Exception as e:
        logger.error(f"Erro ao buscar FIPE para {marca_nome} {modelo_nome} {ano}: {e}")
        return None

# Configuração dinâmica do Host (Local vs Tunel/Produção)
# No Render, basta criar a variável de ambiente NEURA_AI_URL apontando para o seu túnel
host_escolhido = os.getenv("NEURA_AI_URL", "http://127.0.0.1:11434").rstrip("/")

def get_mysql_history(user_id: int, limit: int = 5):
    """Recupera o histórico do MySQL para substituir o SQLite."""
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
            # Inverte para ordem cronológica (neura_ai espera isso)
            for row in reversed(rows):
                if row['mensagem_usuario']:
                    history.append({"role": "user", "content": row['mensagem_usuario']})
                if row['resposta_ia']:
                    history.append({"role": "assistant", "content": row['resposta_ia']})
            return history
    except Exception as e:
        logger.error(f"Erro ao recuperar histórico do MySQL: {e}")
        return []
    finally:
        if 'conn' in locals():
            conn.close()

try:
    # Tenta o modo v0.2.7 (Usando Qwen 2 para maior velocidade em CPU)
    # Desativamos o uso de memória interna SQLite (use_memory=False)
    brain = Neura(
        model="gemma2:2b", 
        system_prompt=SYSTEM_PROMPT, 
        host=host_escolhido,
        use_memory=False
    )
except TypeError:
    # Fallback v0.2.5
    brain = Neura(model="gemma2:2b", system_prompt=SYSTEM_PROMPT, use_memory=False)
    
    # RECONFIGURAÇÃO IMEDIATA
    brain.host = host_escolhido.rstrip('/')
    
    # Define os headers de bypass para o túnel
    bypass_headers = getattr(NeuraConfig, 'BYPASS_HEADERS', {"Bypass-Tunnel-Reminder": "true"})
    headers = bypass_headers if "loca.lt" in brain.host else {}
    
    # Sobrescreve o cliente do Ollama
    brain.client = ollama.Client(host=brain.host, headers=headers)
    logger.info(f"🚀 Host reconfigurado com sucesso (Stateless) para: {brain.host}")


def gerar_resposta(mensagem: str, user_id: int, user_data: dict = None) -> str:
    """
    Gera resposta de texto usando a Neura (Ollama Local ou Túnel).
    O histórico agora é recuperado do MySQL (Aiven) para substituir o SQLite.
    """
    try:
        logger.info(f"NOG Chat: Processando msg do usuário {user_id} via {brain.host}")
        
        # 1. Recupera histórico do MySQL
        historico_mysql = get_mysql_history(user_id)
        
        # 2. Injeta contexto do veículo se disponível
        prompt_final = mensagem
        if user_data and user_data.get("possui_veiculo"):
            contexto_veiculo = (f"\n\n[CONTEXTO DO USUÁRIO]: O usuário possui um(a) {user_data.get('veiculo_tipo')} "
                                f"{user_data.get('veiculo_marca')} {user_data.get('veiculo_modelo')} "
                                f"ano {user_data.get('veiculo_ano_fabricacao')}. "
                                f"Responda considerando este veículo se for relevante.")
            prompt_final = contexto_veiculo + "\n\nPergunta do usuário: " + mensagem

        # 3. Chama a inteligência passando o histórico recuperado
        resposta = brain.get_response(prompt_final, history=historico_mysql)
        
        if not resposta or "Não consegui gerar uma resposta" in resposta:
             logger.warning(f"Aviso: Resposta vazia da Neura para o usuário {user_id}")
             return "⚠️ O NOG está processando muitas informações no momento. Tente reformular sua pergunta."

        return resposta

    except Exception as e:
        logger.error(f"❌ Erro no NOG (nogai.py): {e}", exc_info=True)
        return "❌ Erro local ao processar sua solicitação. Verifique a conexão com o servidor Ollama."