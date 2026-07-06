import json
import logging
import os
from datetime import datetime
from flask import Blueprint, request
from flask_sock import Sock
from flask_jwt_extended import decode_token
from services.nogai import gerar_resposta, gerar_termos_busca
from services.youtube_service import buscar_videos_youtube
from urllib.parse import quote, quote_plus

ws_bp = Blueprint("ws", __name__)
sock = Sock()
logger = logging.getLogger(__name__)


def _save_chat(user_id, session_id, message, response, videos, links, topic):
    try:
        from .routes.database import get_db
        with get_db() as (cur, conn):
            cur.execute(
                """INSERT INTO chats (user_id, session_id, mensagem_usuario, resposta_ia,
                   created_at, videos, links, topic)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (user_id, session_id, message, response, datetime.now(),
                 json.dumps(videos), json.dumps(links), topic),
            )
            conn.commit()
            chat_id = cur.lastrowid
        return chat_id
    except Exception as e:
        logger.warning("Erro ao salvar chat no WebSocket: %s", e, exc_info=True)
        return None


@sock.route("/ws/chat")
def chat_websocket(ws):
    token = request.args.get("token")
    guest_id = request.args.get("guest_id")
    session_id = request.args.get("session_id", "")
    user_id = None

    if token:
        try:
            decoded = decode_token(token)
            user_id = decoded.get("sub")
        except Exception:
            ws.send(json.dumps({"error": "Token invalido"}))
            ws.close()
            return

    while True:
        try:
            raw = ws.receive(timeout=300)
            if raw is None:
                break
            data = json.loads(raw)
            message = data.get("message", "").strip()
            if not message:
                ws.send(json.dumps({"error": "Mensagem vazia"}))
                continue

            sess = data.get("session_id") or session_id

            ws.send(json.dumps({"type": "status", "message": "Processando..."}))

            response = gerar_resposta(message, user_id or 0)

            termos = gerar_termos_busca(message)
            videos = []
            links = []
            if termos.get("youtube"):
                try:
                    videos = buscar_videos_youtube(termos["youtube"])
                except Exception:
                    pass
            if termos.get("loja"):
                links.append({"titulo": f"Ver ofertas de {termos['loja']}", "url": f"https://www.webmotors.com.br/carros/estoque?q={quote_plus(termos['loja'])}", "tipo": "veiculo", "icon": "fas fa-car"})
            if termos.get("pecas"):
                links.append({"titulo": f"Comprar {termos['pecas']} no Mercado Livre", "url": f"https://lista.mercadolivre.com.br/{quote(termos['pecas'].replace(' ', '-'), safe='')}", "tipo": "peca", "icon": "fas fa-tools"})

            topic = termos.get("youtube") or termos.get("loja") or termos.get("pecas") or "Consultoria Geral"
            now_iso = datetime.now().isoformat()

            chat_id = _save_chat(user_id, sess, message, response, videos, links, topic)

            ws.send(json.dumps({
                "type": "response",
                "id": chat_id,
                "mensagem_usuario": message,
                "resposta_ia": response,
                "videos": videos,
                "links": links,
                "topic": topic,
                "created_at": now_iso,
                "session_id": sess,
            }))
        except json.JSONDecodeError:
            ws.send(json.dumps({"error": "JSON invalido"}))
        except Exception as e:
            logger.error("WebSocket error: %s", e, exc_info=True)
            try:
                ws.send(json.dumps({"error": "Erro interno"}))
            except Exception:
                pass
