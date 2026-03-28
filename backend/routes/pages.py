import os
import io
import logging
from datetime import datetime
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
import speech_recognition as sr
from pydub import AudioSegment
from services.nogai import gerar_resposta, get_fipe_value, gerar_termo_busca_youtube, gerar_termo_busca_loja, gerar_termo_busca_pecas
import json
from services.youtube_service import buscar_videos_youtube
from services.web_scraping import WebScraper
from services.vision_ai import analisar_imagem
from services.report_generator import criar_relatorio_pdf
from .database import get_db, is_trial_expired, get_trial_days_remaining

pages_bp = Blueprint('pages', __name__)
logger = logging.getLogger(__name__)

PREMIUM_ONLY_ERROR = "Recurso exclusivo para Premium"

def get_user_by_id(cursor, user_id):
    cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    return cursor.fetchone()

def ensure_premium_user(user):
    if not user:
        return jsonify(error="Usuário não encontrado"), 404
    if not user.get("is_premium"):
        return jsonify(error=PREMIUM_ONLY_ERROR), 403
    return None

@pages_bp.route("/")
def index():
    return current_app.send_static_file("index.html")

@pages_bp.route("/<path:path>")
def serve_html(path):
    if not path.endswith(".html") and "." not in path:
        path += ".html"
    return current_app.send_static_file(path)

@pages_bp.route("/api/user", methods=["GET"])
@jwt_required()
def get_user():
    user_id = get_jwt_identity()
    with get_db() as (cursor, conn):
        cursor.execute("""
            SELECT nome, email, is_premium, created_at, possui_veiculo,
                   veiculo_marca, veiculo_modelo, veiculo_ano_fabricacao,
                   veiculo_ano_compra, veiculo_tipo, is_two_factor_enabled
            FROM users WHERE id = %s
        """, (user_id,))
        user = cursor.fetchone()
        cursor.execute("SELECT COUNT(*) AS total FROM chats WHERE user_id = %s", (user_id,))
        total = cursor.fetchone()
        
        cursor.execute("SELECT id, tipo, marca, modelo, ano_fabricacao, ano_compra FROM veiculos WHERE user_id = %s", (user_id,))
        veiculos = cursor.fetchall()
        
        return jsonify({
            **user,
            "trial_expired": is_trial_expired(user),
            "trial_days_remaining": get_trial_days_remaining(user),
            "is_premium": bool(user["is_premium"]),
            "possui_veiculo": len(veiculos) > 0,
            "veiculos": veiculos,
            "total_consultas": int(total["total"])
        }), 200

@pages_bp.route("/api/user", methods=["PUT"])
@jwt_required()
def update_user():
    user_id = get_jwt_identity()
    data = request.get_json() or {}
    nome = (data.get("nome") or "").strip()
    email = (data.get("email") or "").strip().lower()

    if not nome or not email:
        return jsonify(error="Dados inválidos"), 400

    try:
        with get_db() as (cursor, conn):
            cursor.execute("SELECT id FROM users WHERE email = %s AND id <> %s", (email, user_id))
            if cursor.fetchone():
                return jsonify(error="Email já está em uso"), 409

            cursor.execute("""
                UPDATE users SET 
                    nome = %s, email = %s
                WHERE id = %s
            """, (nome, email, user_id))
            conn.commit()
            
            cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            user = cursor.fetchone()
            
            cursor.execute("SELECT COUNT(*) AS total FROM chats WHERE user_id = %s", (user_id,))
            total = cursor.fetchone()

            return jsonify({
                **user,
                "trial_expired": is_trial_expired(user),
                "trial_days_remaining": get_trial_days_remaining(user),
                "is_premium": bool(user["is_premium"]),
                "total_consultas": int(total["total"]),
                "success": True
            }), 200
    except Exception as e:
        logger.error(f"❌ Erro ao atualizar perfil: {e}")
        return jsonify(error="Erro ao atualizar perfil"), 500

@pages_bp.route("/api/veiculos", methods=["POST"])
@jwt_required()
def add_veiculo():
    user_id = get_jwt_identity()
    data = request.get_json()
    try:
        with get_db() as (cursor, conn):
            ano_fab = data.get("ano_fabricacao")
            ano_compra = data.get("ano_compra")
            ano_fab = int(ano_fab) if ano_fab else None
            ano_compra = int(ano_compra) if ano_compra else None
            
            cursor.execute("""
                INSERT INTO veiculos (user_id, tipo, marca, modelo, ano_fabricacao, ano_compra)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (user_id, data.get("tipo"), data.get("marca"), data.get("modelo"), ano_fab, ano_compra))
            v_id = cursor.lastrowid
            cursor.execute("UPDATE users SET possui_veiculo = TRUE WHERE id = %s", (user_id,))
            return jsonify(success=True, id=v_id), 201
    except Exception as e:
        logger.error(f"Erro ao adicionar veiculo: {e}")
        return jsonify(error="Erro interno ao adicionar veículo"), 500

@pages_bp.route("/api/veiculos/<int:v_id>", methods=["PUT"])
@jwt_required()
def edit_veiculo(v_id):
    user_id = get_jwt_identity()
    data = request.get_json()
    try:
        with get_db() as (cursor, conn):
            cursor.execute("SELECT id FROM veiculos WHERE id = %s AND user_id = %s", (v_id, user_id))
            if not cursor.fetchone():
                return jsonify(error="Veículo não encontrado"), 404
                
            ano_fab = data.get("ano_fabricacao")
            ano_compra = data.get("ano_compra")
            ano_fab = int(ano_fab) if ano_fab else None
            ano_compra = int(ano_compra) if ano_compra else None
            
            cursor.execute("""
                UPDATE veiculos 
                SET tipo = %s, marca = %s, modelo = %s, ano_fabricacao = %s, ano_compra = %s
                WHERE id = %s AND user_id = %s
            """, (data.get("tipo"), data.get("marca"), data.get("modelo"), ano_fab, ano_compra, v_id, user_id))
            return jsonify(success=True), 200
    except Exception as e:
        logger.error(f"Erro ao editar veiculo: {e}")
        return jsonify(error="Erro interno ao editar veículo"), 500

@pages_bp.route("/api/veiculos/<int:v_id>", methods=["DELETE"])
@jwt_required()
def delete_veiculo(v_id):
    user_id = get_jwt_identity()
    try:
        with get_db() as (cursor, conn):
            cursor.execute("DELETE FROM veiculos WHERE id = %s AND user_id = %s", (v_id, user_id))
            if cursor.rowcount == 0:
                return jsonify(error="Veículo não encontrado"), 404
            
            cursor.execute("SELECT COUNT(*) as count FROM veiculos WHERE user_id = %s", (user_id,))
            if cursor.fetchone()["count"] == 0:
                cursor.execute("UPDATE users SET possui_veiculo = FALSE WHERE id = %s", (user_id,))

            return jsonify(success=True), 200
    except Exception as e:
        logger.error(f"Erro ao excluir veiculo: {e}")
        return jsonify(error="Erro interno"), 500

@pages_bp.route("/api/user", methods=["DELETE"])
@jwt_required()
def delete_user():
    user_id = get_jwt_identity()
    try:
        with get_db() as (cursor, conn):
            cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
        return jsonify(success=True), 200
    except Exception as e:
        logger.error(f"❌ Erro ao excluir conta: {e}")
        return jsonify(error="Erro ao excluir conta"), 500

@pages_bp.route("/api/chat", methods=["POST"])
@jwt_required()
def chat():
    user_id = get_jwt_identity()
    data = request.get_json()
    msg, img_b64 = data.get("message"), data.get("image")
    try:
        with get_db() as (cursor, conn):
            user = get_user_by_id(cursor, user_id)
            if is_trial_expired(user): return jsonify(error="TRIAL_EXPIRED"), 402
            
            cursor.execute("SELECT tipo, marca, modelo, ano_fabricacao, ano_compra FROM veiculos WHERE user_id = %s", (user_id,))
            veiculos = cursor.fetchall()
            if veiculos:
                user['lista_veiculos'] = veiculos

            resposta = analisar_imagem(img_b64, msg) if img_b64 else gerar_resposta(msg, user_id, user_data=user)
            
            videos = []
            if not img_b64 and msg:
                # Buscar peças
                termo_pecas = gerar_termo_busca_pecas(msg)
                if termo_pecas:
                    pecas_lojas = WebScraper().search_car_parts(termo_pecas)
                    for loja in pecas_lojas:
                        domain = loja['url'].split('//')[-1].split('/')[0]
                        titulo = f"🔧 {domain}"
                        descricao = f"Busca em lojas de peças sugerida pelo NOG"
                        videos.append({'titulo': titulo, 'url': loja['url'], 'descricao': descricao})
                        cursor.execute("""
                            INSERT INTO videos (user_id, titulo, url, descricao)
                            VALUES (%s, %s, %s, %s)
                        """, (user_id, titulo, loja['url'], descricao))

                # Buscar links de lojas de veículos e salvar na base "videos" (cards)
                termo_loja = gerar_termo_busca_loja(msg)
                if termo_loja:
                    lojas = WebScraper().search_car_stores(termo_loja)
                    for loja in lojas:
                        domain = loja['url'].split('//')[-1].split('/')[0]
                        titulo = f"🛒 {domain}"
                        descricao = f"Busca em lojas web sugerida pelo NOG"
                        videos.append({'titulo': titulo, 'url': loja['url'], 'descricao': descricao})
                        cursor.execute("""
                            INSERT INTO videos (user_id, titulo, url, descricao)
                            VALUES (%s, %s, %s, %s)
                        """, (user_id, titulo, loja['url'], descricao))

                if user.get("is_premium"):
                    termo_busca = gerar_termo_busca_youtube(msg, resposta)
                    if termo_busca:
                        yt_videos = buscar_videos_youtube(termo_busca)
                        for v in yt_videos:
                            videos.append(v)
                            cursor.execute("""
                                INSERT INTO videos (user_id, titulo, url, descricao)
                                VALUES (%s, %s, %s, %s)
                            """, (user_id, v['titulo'], v['url'], "Recomendado pelo NOG IA durante o chat"))
                    
            videos_json = json.dumps(videos) if videos else None
            
            cursor.execute("INSERT INTO chats (user_id, mensagem_usuario, resposta_ia, videos) VALUES (%s, %s, %s, %s)",
                           (user_id, msg or "[Imagem]", resposta, videos_json))
            return jsonify(response=resposta, videos=videos)
    except Exception as e:
        logger.error(f"❌ Erro na rota /api/chat: {e}")
        return jsonify(error="Erro interno ao processar chat."), 500

@pages_bp.route("/api/voice", methods=["POST"])
@jwt_required()
def voice_to_text():
    user_id = get_jwt_identity()
    if 'audio' not in request.files:
        return jsonify(error="Arquivo de áudio não enviado"), 400
    
    audio_file = request.files['audio']
    try:
        audio = AudioSegment.from_file(io.BytesIO(audio_file.read()))
        wav_io = io.BytesIO()
        audio.export(wav_io, format="wav")
        wav_io.seek(0)

        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_io) as source:
            audio_data = recognizer.record(source)
            text = recognizer.recognize_google(audio_data, language="pt-BR")
            
        logger.info(f"🎙️ Voz transcrita para usuário {user_id}: {text}")
        
        with get_db() as (cursor, conn):
            user = get_user_by_id(cursor, user_id)
            
            cursor.execute("SELECT tipo, marca, modelo, ano_fabricacao, ano_compra FROM veiculos WHERE user_id = %s", (user_id,))
            veiculos = cursor.fetchall()
            if veiculos:
                user['lista_veiculos'] = veiculos
            
            resposta = gerar_resposta(text, user_id, user_data=user)
            
            videos = []
            # Buscar peças via voz
            termo_pecas = gerar_termo_busca_pecas(text)
            if termo_pecas:
                pecas_lojas = WebScraper().search_car_parts(termo_pecas)
                for loja in pecas_lojas:
                    domain = loja['url'].split('//')[-1].split('/')[0]
                    titulo = f"🔧 {domain}"
                    descricao = f"Busca em lojas de peças sugerida pelo NOG via áudio"
                    videos.append({'titulo': titulo, 'url': loja['url'], 'descricao': descricao})
                    cursor.execute("""
                        INSERT INTO videos (user_id, titulo, url, descricao)
                        VALUES (%s, %s, %s, %s)
                    """, (user_id, titulo, loja['url'], descricao))

            # Buscar links de lojas de automóveis via voz
            termo_loja = gerar_termo_busca_loja(text)
            if termo_loja:
                lojas = WebScraper().search_car_stores(termo_loja)
                for loja in lojas:
                    domain = loja['url'].split('//')[-1].split('/')[0]
                    titulo = f"🛒 {domain}"
                    descricao = f"Busca em lojas sugerida pelo NOG via áudio"
                    videos.append({'titulo': titulo, 'url': loja['url'], 'descricao': descricao})
                    cursor.execute("""
                        INSERT INTO videos (user_id, titulo, url, descricao)
                        VALUES (%s, %s, %s, %s)
                    """, (user_id, titulo, loja['url'], descricao))
            
            if user.get("is_premium"):
                termo_busca = gerar_termo_busca_youtube(text, resposta)
                if termo_busca:
                    yt_videos = buscar_videos_youtube(termo_busca)
                    for v in yt_videos:
                        videos.append(v)
                        cursor.execute("""
                            INSERT INTO videos (user_id, titulo, url, descricao)
                            VALUES (%s, %s, %s, %s)
                        """, (user_id, v['titulo'], v['url'], "Recomendado pelo NOG IA via comando de voz"))
                
            videos_json = json.dumps(videos) if videos else None
            
            cursor.execute("INSERT INTO chats (user_id, mensagem_usuario, resposta_ia, videos) VALUES (%s, %s, %s, %s)",
                           (user_id, text, resposta, videos_json))
            
            return jsonify(text=text, response=resposta, videos=videos)

    except sr.UnknownValueError:
        return jsonify(error="Não entendi o que você disse"), 422
    except sr.RequestError as e:
        logger.error(f"Erro no serviço de voz do Google: {e}")
        return jsonify(error="Serviço de voz indisponível no momento"), 503
    except Exception as e:
        logger.error(f"Erro no processamento de voz: {e}")
        return jsonify(error="Falha técnica ao processar áudio"), 500

@pages_bp.route("/api/chat/history", methods=["GET"])
@jwt_required()
def get_chat_history():
    user_id = get_jwt_identity()
    try:
        with get_db() as (cursor, conn):
            cursor.execute("""
                SELECT mensagem_usuario, resposta_ia, created_at, videos
                FROM chats 
                WHERE user_id = %s 
                ORDER BY created_at ASC
            """, (user_id,))
            chats = cursor.fetchall()
            for c in chats:
                if isinstance(c['created_at'], datetime):
                    c['created_at'] = c['created_at'].isoformat()
                
                # Parse videos JSON if available
                if c.get('videos'):
                    if isinstance(c['videos'], str):
                        try:
                            c['videos'] = json.loads(c['videos'])
                        except json.JSONDecodeError:
                            c['videos'] = []
                else:
                    c['videos'] = []
                    
            return jsonify(chats=chats), 200
    except Exception as e:
        logger.error(f"❌ Erro ao buscar histórico: {e}")
        return jsonify(error="Erro ao buscar histórico"), 500

@pages_bp.route("/api/dashboard", methods=["GET"])
@jwt_required()
def get_dashboard():
    user_id = get_jwt_identity()
    try:
        with get_db() as (cursor, conn):
            user = get_user_by_id(cursor, user_id)
            premium_error = ensure_premium_user(user)
            if premium_error:
                return premium_error
            
            cursor.execute("SELECT id, tipo, marca, modelo, ano_fabricacao, ano_compra FROM veiculos WHERE user_id = %s", (user_id,))
            veiculos = cursor.fetchall()
            
            if not veiculos:
                return jsonify(error="VEHICLE_NOT_FOUND"), 404
                
            resultados = []
            
            for v in veiculos:
                ano_atual = datetime.now().year
                ano_fab = v["ano_fabricacao"] or ano_atual
                idade = ano_atual - ano_fab
                
                alertas = []
                if idade >= 5:
                    alertas.append({"item": "Suspensão", "status": "Atenção", "msg": "Revisar amortecedores e buchas."})
                if idade >= 3:
                    alertas.append({"item": "Líquido Arrefecimento", "status": "Aviso", "msg": "Troca recomendada a cada 2-3 anos."})
                
                alertas.append({"item": "Pneus", "status": "Ok" if idade < 4 else "Atenção", "msg": "Verificar TWI e validade."})
                alertas.append({"item": "Freios", "status": "Ok", "msg": "Monitorar espessura das pastilhas."})
                
                tipo_map = {
                    "carro": "carros",
                    "moto": "motos",
                    "caminhao": "caminhoes",
                    "caminhão": "caminhoes"
                }
                v_tipo = v.get("tipo") or "carro"
                tipo_fipe = tipo_map.get(v_tipo.lower(), "carros")
                
                dados_fipe = get_fipe_value(
                    tipo_fipe, 
                    v["marca"], 
                    v["modelo"], 
                    ano_fab
                )
                
                if dados_fipe:
                    preco_fipe = dados_fipe.get("Valor", "N/A")
                    mes_fipe = dados_fipe.get("MesReferencia", datetime.now().strftime("%B %Y"))
                else:
                    valor_base = 80000 if v_tipo == "carro" else 30000
                    valor_estimado = valor_base * (0.92 ** idade)
                    preco_fipe = f"R$ {valor_estimado:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                    mes_fipe = f"{datetime.now().strftime('%B %Y')} (Estimado)"
                
                resultados.append({
                    "id": v["id"],
                    "veiculo": {
                        "marca": v["marca"],
                        "modelo": v["modelo"],
                        "ano": ano_fab,
                        "tipo": v_tipo
                    },
                    "saude": alertas,
                    "fipe": {
                        "preco": preco_fipe,
                        "mes": mes_fipe
                    }
                })
            
            return jsonify(resultados), 200
    except Exception as e:
        logger.error(f"❌ Erro no dashboard: {e}")
        return jsonify(error="Erro ao carregar dashboard"), 500

@pages_bp.route("/api/report", methods=["POST"])
@jwt_required()
def generate_report_endpoint():
    user_id = get_jwt_identity()
    data = request.get_json()
    text_content = data.get("text")
    
    if not text_content:
        return jsonify(error="Conteúdo do relatório vazio"), 400

    try:
        with get_db() as (cursor, conn):
            user = get_user_by_id(cursor, user_id)
            premium_error = ensure_premium_user(user)
            if premium_error:
                return premium_error
        
        report_dir = os.path.join(current_app.static_folder, 'reports')
        if not os.path.exists(report_dir):
            os.makedirs(report_dir)

        filename = f"laudo_{user_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf"
        filepath = os.path.join(report_dir, filename)
        
        criar_relatorio_pdf(user, text_content, filepath)
        
        return jsonify(url=f"/reports/{filename}"), 200
    except Exception as e:
        logger.error(f"❌ Erro ao gerar relatório: {e}")
        return jsonify(error="Falha na geração do PDF"), 500

@pages_bp.route("/api/videos", methods=["GET"])
@jwt_required()
def get_videos():
    user_id = get_jwt_identity()
    try:
        with get_db() as (cursor, conn):
            user = get_user_by_id(cursor, user_id)
            premium_error = ensure_premium_user(user)
            if premium_error:
                return premium_error

            cursor.execute("""
                SELECT id, titulo, url, descricao, created_at
                FROM videos
                WHERE user_id = %s
                ORDER BY created_at DESC
            """, (user_id,))
            videos = cursor.fetchall()
            for v in videos:
                if isinstance(v['created_at'], datetime):
                    v['created_at'] = v['created_at'].isoformat()
            return jsonify(videos=videos), 200
    except Exception as e:
        logger.error(f"❌ Erro ao buscar vídeos: {e}")
        return jsonify(error="Erro ao buscar vídeos"), 500

@pages_bp.route("/api/videos", methods=["POST"])
@jwt_required()
def add_video():
    user_id = get_jwt_identity()
    data = request.get_json() or {}
    titulo = (data.get("titulo") or "").strip()
    url = (data.get("url") or "").strip()
    descricao = (data.get("descricao") or "").strip()

    if not titulo or not url:
        return jsonify(error="Título e URL são obrigatórios"), 400

    try:
        with get_db() as (cursor, conn):
            user = get_user_by_id(cursor, user_id)
            premium_error = ensure_premium_user(user)
            if premium_error:
                return premium_error

            cursor.execute("""
                INSERT INTO videos (user_id, titulo, url, descricao)
                VALUES (%s, %s, %s, %s)
            """, (user_id, titulo, url, descricao))
            video_id = cursor.lastrowid
            
            cursor.execute("SELECT * FROM videos WHERE id = %s", (video_id,))
            video = cursor.fetchone()
            if isinstance(video['created_at'], datetime):
                video['created_at'] = video['created_at'].isoformat()
                
            return jsonify(video=video, success=True), 201
    except Exception as e:
        logger.error(f"❌ Erro ao adicionar vídeo: {e}")
        return jsonify(error="Erro ao adicionar vídeo"), 500

@pages_bp.route("/api/videos/<int:video_id>", methods=["DELETE"])
@jwt_required()
def delete_video(video_id):
    user_id = get_jwt_identity()
    try:
        with get_db() as (cursor, conn):
            user = get_user_by_id(cursor, user_id)
            premium_error = ensure_premium_user(user)
            if premium_error:
                return premium_error
            # Verifica se o vídeo pertence ao usuário
            cursor.execute("SELECT id FROM videos WHERE id = %s AND user_id = %s", (video_id, user_id))
            if not cursor.fetchone():
                return jsonify(error="Vídeo não encontrado ou acesso negado"), 404
                
            cursor.execute("DELETE FROM videos WHERE id = %s AND user_id = %s", (video_id, user_id))
            return jsonify(success=True), 200
    except Exception as e:
        logger.error(f"❌ Erro ao deletar vídeo: {e}")
        return jsonify(error="Erro ao deletar vídeo"), 500

