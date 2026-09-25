"""Split de routes/pages.py — módulo pages_videos (P1).

Carregado via exec() em routes/pages.py compartilhando os mesmos globals
(imports, pages_bp, constantes, logger). Não importar diretamente.
"""

from typing import TYPE_CHECKING
if TYPE_CHECKING:  # noqa: F401 — nomes providos em runtime pelos globals de routes/pages.py (exec)
    from routes.database import get_db
    from flask_jwt_extended import get_jwt_identity
    import json
    from flask import jsonify
    from flask_jwt_extended import jwt_required
    from flask import request
    from .pages_users import ensure_premium_user, get_user_by_id
    from ..pages import logger, pages_bp

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

            cursor.execute("SELECT * FROM videos WHERE user_id = %s ORDER BY created_at DESC", (user_id,))
            rows = cursor.fetchall()
            return jsonify(videos=rows), 200
    except Exception as e:
        logger.error(f"Erro ao buscar videos: {e}")
        return jsonify(error="Erro interno"), 500


@pages_bp.route("/api/videos", methods=["POST"])
@jwt_required()
def add_video():
    user_id = get_jwt_identity()
    data = request.get_json()
    titulo = data.get("titulo")
    url = data.get("url")
    descricao = data.get("descricao", "")

    if not titulo or not url:
        return jsonify(error="Título e URL são obrigatórios"), 400

    try:
        with get_db() as (cursor, conn):
            user = get_user_by_id(cursor, user_id)
            premium_error = ensure_premium_user(user)
            if premium_error:
                return premium_error

            cursor.execute(
                "INSERT INTO videos (user_id, titulo, url, descricao) VALUES (%s, %s, %s, %s)",
                (user_id, titulo, url, descricao)
            )
            conn.commit()
        return jsonify(success=True), 201
    except Exception as e:
        logger.error(f"Erro ao adicionar video: {e}")
        return jsonify(error="Erro interno"), 500


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

            cursor.execute("DELETE FROM videos WHERE id = %s AND user_id = %s", (video_id, user_id))
            conn.commit()
        return jsonify(success=True), 200
    except Exception as e:
        logger.error(f"Erro ao excluir video: {e}")
        return jsonify(error="Erro interno"), 500


@pages_bp.route("/api/videos/library", methods=["GET"])
@jwt_required()
def get_video_library():
    """Consolida todos os vídeos e links recebidos no chat agrupados por tópico."""
    user_id = get_jwt_identity()
    try:
        with get_db() as (cursor, conn):
            user = get_user_by_id(cursor, user_id)
            premium_error = ensure_premium_user(user)
            if premium_error:
                return premium_error

            cursor.execute("""
                SELECT topic, videos, links, created_at
                FROM chats
                WHERE user_id = %s AND (videos != '[]' OR links != '[]')
                ORDER BY created_at DESC
            """, (user_id,))
            rows = cursor.fetchall()

            library = {}
            for row in rows:
                topic = row['topic'] or "Outros"
                if topic not in library:
                    library[topic] = {"videos": [], "links": [], "date": row['created_at']}

                v_list = json.loads(row['videos']) if row['videos'] else []
                l_list = json.loads(row['links']) if row['links'] else []

                # Evitar duplicatas no mesmo tópico
                for v in v_list:
                    if not any(item['url'] == v['url'] for item in library[topic]["videos"]):
                        library[topic]["videos"].append(v)

                for l in l_list:
                    if not any(item['url'] == l['url'] for item in library[topic]["links"]):
                        library[topic]["links"].append(l)

            # Converter para lista para o frontend
            result = []
            for topic, data in library.items():
                if data["videos"] or data["links"]:
                    result.append({
                        "topic": topic,
                        "videos": data["videos"],
                        "links": data["links"],
                        "last_updated": data["date"]
                    })

            return jsonify(library=result), 200
    except Exception as e:
        logger.error(f"Erro na biblioteca de videos: {e}")
        return jsonify(error="Erro ao carregar biblioteca"), 500

