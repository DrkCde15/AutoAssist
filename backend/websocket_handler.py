import json
import logging
from flask import Blueprint, request
from flask_sock import Sock
from flask_jwt_extended import decode_token

ws_bp = Blueprint("ws", __name__)
sock = Sock()
logger = logging.getLogger(__name__)


@sock.route("/ws/chat")
def chat_websocket(ws):
    token = request.args.get("token")
    guest_id = request.args.get("guest_id")
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

            from services.nogai import gerar_resposta, gerar_termos_busca
            from services.youtube_service import buscar_videos_youtube
            from urllib.parse import quote, quote_plus

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

            ws.send(json.dumps({
                "type": "response",
                "mensagem_usuario": message,
                "resposta_ia": response,
                "videos": videos,
                "links": links,
                "topic": termos.get("youtube") or termos.get("loja") or termos.get("pecas") or "Consultoria Geral",
                "created_at": __import__('datetime').datetime.now().isoformat(),
            }))
        except json.JSONDecodeError:
            ws.send(json.dumps({"error": "JSON invalido"}))
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
            ws.send(json.dumps({"error": "Erro interno"}))
