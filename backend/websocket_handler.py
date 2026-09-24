import json
import logging
import os
import unicodedata
from datetime import datetime
from flask import Blueprint, request
from flask_sock import Sock
from flask_jwt_extended import decode_token, get_jwt_identity
from services.nogai import gerar_resposta, gerar_termos_busca
from services.web_scraping import WebScraper
from services.youtube_service import buscar_videos_youtube
from simple_websocket.errors import ConnectionClosed

ws_bp = Blueprint("ws", __name__)
sock = Sock()
logger = logging.getLogger(__name__)


def _normalize_text(text):
    """Remove acentos e minúsculas para casar palavras-chave ("mecânico" == "mecanic")."""
    normalized = unicodedata.normalize("NFD", str(text or "").lower())
    return "".join(c for c in normalized if unicodedata.category(c) != "Mn")


def _load_user_data(user_id):
    try:
        from routes.database import get_db
        from routes.pages import load_user_chat_context
        with get_db() as (cur, conn):
            return load_user_chat_context(cur, user_id)
    except Exception:
        return None

def _save_chat(user_id, session_id, message, response, videos, links, topic):
    try:
        from routes.database import get_db
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
    guest_id = None
    session_id = None
    user_id = None

    # Autentica via primeiro frame (auth handshake) em vez de query string
    try:
        raw = ws.receive(timeout=10)
        if raw is None:
            return
        auth = json.loads(raw)
        if auth.get("type") == "auth":
            token = auth.get("token")
            guest_id = auth.get("guest_id")
            session_id = auth.get("session_id", "")
            try:
                cookie_identity = get_jwt_identity()
                if cookie_identity:
                    user_id = cookie_identity
            except Exception:
                pass
            if not user_id and token:
                try:
                    decoded = decode_token(token)
                    user_id = decoded.get("sub")
                except Exception:
                    ws.send(json.dumps({"error": "Token invalido"}))
                    ws.close()
                    return

            # Visitante anônimo: exige Turnstile para proteger o custo da IA
            if not user_id:
                from utils.turnstile import (
                    turnstile_enabled,
                    verify_turnstile,
                    expected_hostnames,
                )
                if turnstile_enabled():
                    secret = os.getenv("TURNSTILE_SECRET_KEY", "")
                    t_token = auth.get("turnstile_token") or ""
                    if not t_token or not verify_turnstile(
                        secret, t_token, "chat", expected_hostnames(), None
                    ):
                        ws.send(json.dumps({"error": "Verificação de segurança pendente."}))
                        ws.close()
                        return
        else:
            ws.send(json.dumps({"error": "Primeira mensagem deve ser de autenticacao"}))
            ws.close()
            return
    except Exception:
        ws.send(json.dumps({"error": "Falha na autenticacao"}))
        ws.close()
        return

    while True:
        try:
            raw = ws.receive(timeout=300)
            if raw is None:
                break
            data = json.loads(raw)
            # P2: rate-limit por usuário/guest no WS (20/min)
            try:
                from utils.rate_limit import ws_chat_allowed
                _rl_uid = user_id
                _rl_guest = guest_id or data.get("guest_id")
                if not ws_chat_allowed(_rl_uid, _rl_guest):
                    ws.send(json.dumps({"error": "Limite de mensagens excedido. Aguarde um minuto."}))
                    continue
            except Exception:
                pass
            message = data.get("message", "").strip()
            attachment_raw = data.get("attachment")
            image_b64 = data.get("image")
            if not message and not attachment_raw and not image_b64:
                ws.send(json.dumps({"error": "Mensagem vazia"}))
                continue

            sess = data.get("session_id") or session_id

            ws.send(json.dumps({"type": "status", "message": "Processando..."}))

            user_data = _load_user_data(user_id) if user_id else None

            attachment = None
            if attachment_raw:
                try:
                    from routes.pages import parse_chat_attachment
                    attachment = parse_chat_attachment({"attachment": attachment_raw})
                except ValueError as exc:
                    ws.send(json.dumps({"error": str(exc)}))
                    continue
                except Exception:
                    ws.send(json.dumps({"error": "Arquivo anexado inválido."}))
                    continue

            # Passa localização do usuário para o contexto do chatbot
            if not isinstance(user_data, dict):
                user_data = {}
            user_data["lat"] = data.get("lat")
            user_data["lng"] = data.get("lng")

            reference_images = []
            vehicle_id = data.get("vehicle_id")
            if user_id and vehicle_id and (attachment or image_b64):
                try:
                    from routes.database import get_db
                    from routes.pages import get_vehicle_reference_images
                    with get_db() as (cur, conn):
                        reference_images = get_vehicle_reference_images(cur, user_id, vehicle_id)
                except Exception:
                    reference_images = []

            if attachment or image_b64:
                from routes.pages import generate_assistant_payload
                response, videos, links, topic = generate_assistant_payload(
                    message,
                    user_id or 0,
                    user_data or {},
                    [],
                    image_b64=image_b64,
                    attachment=attachment,
                    reference_images=reference_images,
                )
                if vehicle_id and user_id:
                    seed_b64 = image_b64
                    if not seed_b64 and attachment and attachment.get("kind") == "image":
                        import base64 as _b64mod
                        seed_b64 = (
                            "data:" + attachment["mime_type"] + ";base64,"
                            + _b64mod.b64encode(attachment["data"]).decode("ascii")
                        )
                    if seed_b64:
                        try:
                            from routes.database import get_db
                            from routes.pages import seed_vehicle_photo_if_missing
                            with get_db() as (cur, conn):
                                seed_vehicle_photo_if_missing(cur, conn, user_id, vehicle_id, seed_b64)
                        except Exception:
                            pass
            else:
                response = gerar_resposta(message, user_id or 0, user_data=user_data)

                _MECH_KEYWORDS = ["mecanic", "oficina", "borracheiro", "funileiro",
                                  "reparo", "consertar", "arrumar", "troca de oleo",
                                  "troque oleo", "trocar oleo", "alinhamento",
                                  "balanceamento", "revisao"]
                is_mechanic_query = any(kw in _normalize_text(message) for kw in _MECH_KEYWORDS)

                videos = []
                links = []
                topic = "Consultoria Geral"

                if not is_mechanic_query:
                    termos = gerar_termos_busca(message)
                    if termos.get("youtube"):
                        try:
                            videos = buscar_videos_youtube(termos["youtube"])
                        except Exception:
                            pass
                    if termos.get("loja"):
                        try:
                            scraper = WebScraper()
                            lojas = scraper.search_car_stores(termos["loja"])
                            for loja in lojas:
                                loja.setdefault("tipo", "veiculo")
                                loja.setdefault("icon", "fas fa-car")
                            links.extend(lojas)
                        except Exception:
                            pass
                    if termos.get("pecas"):
                        try:
                            scraper = WebScraper()
                            pecas = scraper.search_car_parts(termos["pecas"])
                            for peca in pecas:
                                peca.setdefault("tipo", "peca")
                                peca.setdefault("icon", "fas fa-tools")
                            links.extend(pecas)
                        except Exception:
                            pass
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
        except ConnectionClosed:
            logger.info("WebSocket disconnected (client closed connection)")
            break
        except Exception as e:
            logger.error("WebSocket error: %s", e, exc_info=True)
            try:
                ws.send(json.dumps({"error": "Erro interno"}))
            except Exception:
                pass
