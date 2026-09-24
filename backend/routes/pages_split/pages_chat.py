"""Split de routes/pages.py — módulo pages_chat (P1).

Carregado via exec() em routes/pages.py compartilhando os mesmos globals
(imports, pages_bp, constantes, logger). Não importar diretamente.
"""

def _emit_usage_events(*, user_id, anonymous_id, is_raio):
    """Emite eventos de uso do funil (NOG / Raio-X) de forma idempotente.

    ``first_*`` é decidido por dados persistidos (has_prior_event), nunca
    por estado de memória. Não lança exceção para não impactar a resposta
    de chat/voz já gerada com sucesso.
    """
    identity_uid = user_id
    identity_aid = anonymous_id if not user_id else None
    if not identity_uid and not identity_aid:
        return
    try:
        # "primeiro" é decidido ANTES de emitir o evento de uso, para não
        # contar o próprio evento recém-inserido como prévio.
        is_first_nog = not has_prior_event("nog_use", user_id=identity_uid, anonymous_id=identity_aid)
        record_analytics_event(
            "nog_use",
            user_id=identity_uid,
            anonymous_id=identity_aid,
            path="/api/chat",
            metadata={"mode": "image" if is_raio else "text"},
        )
        if is_first_nog:
            record_analytics_event(
                "first_nog_use",
                user_id=identity_uid,
                anonymous_id=identity_aid,
                path="/api/chat",
                metadata={},
            )
        if is_raio:
            is_first_raio = not has_prior_event("raio_x_use", user_id=identity_uid, anonymous_id=identity_aid)
            record_analytics_event(
                "raio_x_use",
                user_id=identity_uid,
                anonymous_id=identity_aid,
                path="/api/chat",
                metadata={"mode": "image"},
            )
            if is_first_raio:
                record_analytics_event(
                    "first_raio_x",
                    user_id=identity_uid,
                    anonymous_id=identity_aid,
                    path="/api/chat",
                    metadata={},
                )
    except Exception as exc:
        logger.warning("Falha ao emitir eventos de uso (nog/raio): %s", exc)


def normalize_chat_text(value):
    normalized = unicodedata.normalize("NFD", (value or "").lower())
    return "".join(char for char in normalized if unicodedata.category(char) != "Mn")


def is_generic_chat_message(message):
    normalized = normalize_chat_text(message)
    tokens = re.findall(r"[a-z0-9]+", normalized)
    return bool(tokens) and len(tokens) <= 5 and all(token in GENERIC_CHAT_TOKENS for token in tokens)


def get_optional_user_id():
    try:
        verify_jwt_in_request(optional=True)
        return get_jwt_identity()
    except Exception as exc:
        logger.info("Sessao opcional ignorada no chat publico: %s", exc)
        return None


def normalize_guest_id(raw_guest_id):
    guest_id = (raw_guest_id or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{16,128}", guest_id):
        return guest_id
    return None


def hash_guest_id(guest_id):
    return hashlib.sha256(guest_id.encode("utf-8")).hexdigest()


def ensure_guest_chat_usage_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS guest_chat_usage (
            guest_id_hash CHAR(64) PRIMARY KEY,
            message_count INT NOT NULL DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        )
    """)


def reserve_guest_message(cursor, guest_id):
    ensure_guest_chat_usage_table(cursor)
    guest_id_hash = hash_guest_id(guest_id)
    cursor.execute(
        "SELECT message_count FROM guest_chat_usage WHERE guest_id_hash = %s",
        (guest_id_hash,)
    )
    row = cursor.fetchone()
    current_count = int((row or {}).get("message_count") or 0)
    if current_count >= GUEST_CHAT_LIMIT:
        return None

    cursor.execute(
        """
        INSERT INTO guest_chat_usage (guest_id_hash, message_count)
        VALUES (%s, 1)
        ON DUPLICATE KEY UPDATE message_count = message_count + 1
        """,
        (guest_id_hash,)
    )
    return max(0, GUEST_CHAT_LIMIT - current_count - 1)


def parse_json_list(value):
    if isinstance(value, list):
        return value
    if not isinstance(value, str) or not value:
        return []
    try:
        parsed = json.loads(value)
    except Exception:
        return []
    return parsed if isinstance(parsed, list) else []


def parse_history_limit(raw_limit):
    try:
        limit = int(raw_limit or DEFAULT_CHAT_HISTORY_LIMIT)
    except (TypeError, ValueError):
        return DEFAULT_CHAT_HISTORY_LIMIT
    return max(1, min(limit, MAX_CHAT_HISTORY_LIMIT))


def parse_after_id(raw_after_id):
    try:
        after_id = int(raw_after_id or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, after_id)


def decode_attachment_data(data_url):
    if not isinstance(data_url, str) or "," not in data_url:
        raise ValueError("Arquivo anexado inválido.")

    header, encoded = data_url.split(",", 1)
    mime_type = ""
    if header.startswith("data:"):
        mime_type = header[5:].split(";", 1)[0].strip().lower()

    try:
        return mime_type, base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise ValueError("Não foi possível ler o arquivo anexado.") from exc


def infer_attachment_mime_type(filename, provided_type, data_url_type):
    guessed_type = mimetypes.guess_type(filename or "")[0]
    mime_type = (provided_type or data_url_type or guessed_type or "").strip().lower()
    if mime_type == "text/x-markdown":
        return "text/markdown"
    if mime_type in ("application/x-json", "text/json"):
        return "application/json"
    return mime_type


def is_supported_attachment_type(mime_type):
    return (
        mime_type in IMAGE_ATTACHMENT_TYPES
        or mime_type in BINARY_ATTACHMENT_TYPES
        or mime_type in TEXT_ATTACHMENT_TYPES
    )


def parse_chat_attachment(data):
    raw_attachment = data.get("attachment")
    if raw_attachment is None and isinstance(data.get("attachments"), list) and data["attachments"]:
        raw_attachment = data["attachments"][0]
    if not isinstance(raw_attachment, dict):
        return None

    raw_filename = (raw_attachment.get("name") or "anexo").replace("\\", "/").strip()
    if not raw_filename:
        raise ValueError("Nome do arquivo vazio.")
    filename = os.path.basename(raw_filename)[:MAX_FILENAME_LENGTH] or "anexo"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    # Validacao de extensao
    if ext and ext not in ALLOWED_ATTACHMENT_EXTENSIONS:
        raise ValueError(f"Extensao .{ext} nao permitida. Use: {', '.join(sorted(ALLOWED_ATTACHMENT_EXTENSIONS))}")

    # Protecao contra path traversal
    if ".." in raw_filename or raw_filename.startswith("/") or raw_filename.startswith("\\"):
        raise ValueError("Nome de arquivo invalido.")

    data_url_type, file_data = decode_attachment_data(raw_attachment.get("data") or "")
    mime_type = infer_attachment_mime_type(filename, raw_attachment.get("type"), data_url_type)

    # Validacao MIME contra extensao (um MIME pode ter varias extensoes validas)
    mime_to_exts = {
        "image/jpeg": {"jpg", "jpeg"},
        "image/png": {"png"},
        "image/webp": {"webp"},
        "image/gif": {"gif"},
        "application/pdf": {"pdf"},
        "text/plain": {"txt"},
        "text/csv": {"csv"},
        "text/markdown": {"md", "markdown"},
        "application/json": {"json"},
    }
    expected_exts = mime_to_exts.get(mime_type)
    if expected_exts and ext and ext not in expected_exts:
        logger.warning(f"MIME mismatch: {mime_type} vs extensao .{ext}")

    if len(file_data) > MAX_ATTACHMENT_BYTES:
        raise ValueError(f"O arquivo anexado deve ter no maximo {MAX_ATTACHMENT_BYTES // (1024*1024)} MB.")
    if len(file_data) == 0:
        raise ValueError("O arquivo anexado esta vazio.")
    if not is_supported_attachment_type(mime_type):
        raise ValueError("Formato nao suportado. Envie imagem PNG/JPG/WebP/GIF, PDF, TXT, CSV, Markdown ou JSON.")

    # Validacao extra para imagens (dimensoes)
    if mime_type in IMAGE_ATTACHMENT_TYPES:
        try:
            from PIL import Image
            import io
            img = Image.open(io.BytesIO(file_data))
            if img.width > MAX_IMAGE_DIMENSIONS[0] or img.height > MAX_IMAGE_DIMENSIONS[1]:
                raise ValueError(f"Dimensoes da imagem excedem o limite de {MAX_IMAGE_DIMENSIONS[0]}x{MAX_IMAGE_DIMENSIONS[1]}px.")
            img.verify()
        except ValueError:
            raise
        except Exception as e:
            logger.warning(f"Falha ao validar imagem: {e}")

    kind = "text" if mime_type in TEXT_ATTACHMENT_TYPES else "binary"
    if mime_type in IMAGE_ATTACHMENT_TYPES:
        kind = "image"

    return {
        "name": filename,
        "mime_type": mime_type,
        "size": len(file_data),
        "data": file_data,
        "kind": kind,
    }


def attachment_metadata(attachment):
    if not attachment:
        return []
    return [{
        "name": attachment["name"],
        "type": attachment["mime_type"],
        "size": attachment["size"],
    }]


def build_text_attachment_message(message, attachment):
    text = attachment["data"].decode("utf-8", errors="replace").strip()
    if not text:
        raise ValueError("O arquivo de texto anexado está vazio.")

    clipped_text = text[:TEXT_ATTACHMENT_LIMIT]
    omitted_notice = "\n\n[Conteúdo cortado para análise.]" if len(text) > TEXT_ATTACHMENT_LIMIT else ""
    question = (message or "").strip() or "Analise o arquivo anexado e destaque os pontos automotivos relevantes."
    return (
        f"{question}\n\n"
        f"Arquivo anexado: {attachment['name']} ({attachment['mime_type']}).\n"
        f"Conteúdo do arquivo:\n{clipped_text}{omitted_notice}"
    )


def normalize_client_history(raw_history):
    if not isinstance(raw_history, list):
        return []

    history = []
    for item in raw_history[-8:]:
        if not isinstance(item, dict):
            continue

        role = item.get("role")
        content = (item.get("content") or "").strip()
        if role not in ("user", "model") or not content:
            continue

        history.append({"role": role, "content": content[:4000]})

    return history


def build_recommendations(message, historico_recente, default_topic="Consultoria Geral"):
    if not (message or "").strip():
        return [], [], default_topic
    if is_generic_chat_message(message):
        return [], [], default_topic

    _MECH_KEYWORDS = ["mecanic", "oficina", "borracheiro", "funileiro",
                      "reparo", "consertar", "arrumar", "trocar oleo",
                      "alinhamento", "balanceamento", "revisao"]
    if any(kw in message.lower() for kw in _MECH_KEYWORDS):
        return [], [], "Busca de Mecânicos"

    from services.nogai import gerar_termos_busca
    from services.youtube_service import buscar_videos_youtube

    termos = gerar_termos_busca(message, historico=historico_recente)
    termo_yt = termos.get("youtube")
    termo_loja = termos.get("loja")
    termo_pecas = termos.get("pecas")

    videos = []
    links = []

    if termo_yt:
        try:
            videos = buscar_videos_youtube(termo_yt)
        except Exception as e:
            logger.warning(f"Erro ao buscar videos: {e}")

    if termo_loja:
        try:
            scraper = WebScraper()
            lojas = scraper.search_car_stores(termo_loja)
            for loja in lojas:
                loja.setdefault("tipo", "veiculo")
                loja.setdefault("icon", "fas fa-car")
            links.extend(lojas)
        except Exception as e:
            logger.warning(f"Erro ao buscar links de loja: {e}")

    if termo_pecas:
        try:
            scraper = WebScraper()
            pecas = scraper.search_car_parts(termo_pecas)
            for peca in pecas:
                peca.setdefault("tipo", "peca")
                peca.setdefault("icon", "fas fa-tools")
            links.extend(pecas)
        except Exception as e:
            logger.warning(f"Erro ao buscar links de peças: {e}")

    topic = termo_yt or termo_loja or termo_pecas or default_topic

    if links:
        try:
            from services.web_scraping import validate_links
            links = validate_links(links)
        except Exception as e:
            logger.warning(f"Erro na validação de links: {e}")

    return videos, links, topic


def generate_assistant_payload(
    message,
    user_id,
    user,
    historico_recente,
    image_b64=None,
    attachment=None,
    default_topic="Consultoria Geral",
    reference_images=None,
):
    prompt_message = message
    if attachment and attachment["kind"] == "text":
        prompt_message = build_text_attachment_message(message, attachment)

    if attachment and attachment["kind"] in ("image", "binary"):
        from services.attachment_ai import analisar_arquivo
        resposta = analisar_arquivo(
            attachment["data"],
            attachment["mime_type"],
            attachment["name"],
            message,
        )
        videos, links, topic = [], [], default_topic
        return resposta, videos, links, topic

    if image_b64:
        from services.vision_ai import analisar_imagem
        resposta = analisar_imagem(image_b64, message, reference_images=reference_images)
        videos, links, topic = [], [], default_topic
        return resposta, videos, links, topic

    from services.nogai import gerar_resposta
    resposta = gerar_resposta(
        prompt_message,
        user_id,
        user_data=user,
        historico=historico_recente,
    )
    videos, links, topic = build_recommendations(message, historico_recente, default_topic)

    return resposta, videos, links, topic or default_topic


def resolve_recommendations(recommendations_future, default_topic):
    if recommendations_future is None:
        return [], [], default_topic

    try:
        return recommendations_future.result()
    except Exception as exc:
        logger.warning("Recomendações indisponíveis: %s", exc)
        return [], [], default_topic


def serialize_datetime_field(value):
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def normalize_chat_session_id(raw_session_id):
    session_id = (raw_session_id or "").strip()
    if not session_id:
        return None
    return session_id[:50]


def parse_client_created_at(value):
    if isinstance(value, datetime):
        parsed = value
    else:
        text = (value or "").strip()
        if not text:
            return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed.strftime("%Y-%m-%d %H:%M:%S")


def serialize_chat_row(row):
    videos = parse_json_list(row.get("videos"))
    links = parse_json_list(row.get("links"))
    attachments = parse_json_list(row.get("attachments"))

    if is_generic_chat_message(row["mensagem_usuario"]):
        videos = []
        links = []

    return {
        "id": row["id"],
        "session_id": row.get("session_id") or "",
        "mensagem_usuario": row["mensagem_usuario"],
        "resposta_ia": row["resposta_ia"],
        "created_at": serialize_datetime_field(row["created_at"]),
        "videos": videos,
        "links": links,
        "topic": row.get("topic") or "",
        "attachments": attachments,
    }


def format_chat_date(value):
    if not value:
        return "-"
    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y")
    try:
        return datetime.fromisoformat(str(value)).strftime("%d/%m/%Y")
    except ValueError:
        return str(value)


def format_chat_money(value):
    if value is None:
        return "R$ 0,00"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "R$ 0,00"
    return f"R$ {number:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def format_vehicle_for_chat(vehicle):
    label = " ".join(
        str(vehicle.get(field) or "").strip()
        for field in ("tipo", "marca", "modelo")
        if str(vehicle.get(field) or "").strip()
    ) or f"Veiculo #{vehicle.get('id')}"
    details = []
    if vehicle.get("ano_fabricacao"):
        details.append(f"ano {vehicle.get('ano_fabricacao')}")
    if vehicle.get("quilometragem") is not None:
        details.append(f"{vehicle.get('quilometragem')} km")
    return f"{label} ({', '.join(details)})" if details else label


def build_user_chat_data_context(cursor, user_id, veiculos):
    lines = []
    if veiculos:
        lines.append("Dashboard - veiculos cadastrados: " + "; ".join(format_vehicle_for_chat(v) for v in veiculos[:5]))
    else:
        lines.append("Dashboard - nenhum veiculo cadastrado para este usuario.")

    cursor.execute(
        """
        SELECT COUNT(*) AS quantidade_registros,
               COALESCE(SUM(cost), 0) AS total_gastos,
               MAX(service_date) AS ultima_manutencao
        FROM maintenance_history
        WHERE user_id = %s
        """,
        (user_id,)
    )
    summary = cursor.fetchone() or {}
    lines.append(
        "Dashboard - anotacoes de manutencao: "
        f"{int(summary.get('quantidade_registros') or 0)} registro(s), "
        f"total gasto {format_chat_money(summary.get('total_gastos'))}, "
        f"ultima manutencao {format_chat_date(summary.get('ultima_manutencao'))}."
    )

    try:
        alerts = fetch_user_maintenance_alerts(cursor, user_id, only_actionable=True)[:4]
    except Exception as exc:
        logger.warning("Contexto de alertas indisponivel para o chat: %s", exc)
        alerts = []
    if alerts:
        lines.append(
            "Alertas ativos das anotacoes: "
            + " | ".join(f"{a.get('item')}: {a.get('msg')}" for a in alerts)
        )

    cursor.execute(
        """
        SELECT mh.description, mh.maintenance_label, mh.service_date, mh.service_km,
               mh.cost, v.marca AS vehicle_marca, v.modelo AS vehicle_modelo
        FROM maintenance_history mh
        LEFT JOIN veiculos v ON v.id = mh.vehicle_id
        WHERE mh.user_id = %s
        ORDER BY mh.service_date DESC, mh.created_at DESC
        LIMIT 5
        """,
        (user_id,)
    )
    notes = cursor.fetchall()
    if notes:
        note_parts = []
        for note in notes:
            vehicle_label = " ".join(
                str(note.get(field) or "").strip()
                for field in ("vehicle_marca", "vehicle_modelo")
                if str(note.get(field) or "").strip()
            )
            note_parts.append(
                f"{format_chat_date(note.get('service_date'))}: "
                f"{note.get('maintenance_label') or 'Manutencao'}"
                f"{f' em {vehicle_label}' if vehicle_label else ''}"
                f" - {note.get('description')}"
            )
        lines.append("Anotacoes recentes do usuario: " + " | ".join(note_parts))

    predictions = []
    for vehicle in veiculos[:3]:
        try:
            prediction = _predictor().predict_next(
                vehicle_id=vehicle["id"],
                maintenance_type="troca_oleo",
                kilometers_actual=vehicle.get("quilometragem"),
            )
        except Exception as exc:
            logger.warning("Predicao ML indisponivel para veiculo %s: %s", vehicle.get("id"), exc)
            prediction = None

        if prediction:
            predictions.append(
                f"{format_vehicle_for_chat(vehicle)}: proxima referencia em "
                f"{prediction.get('predicted_next_km')} km ou {prediction.get('predicted_next_date')} "
                f"(confianca {prediction.get('confidence')}, modelo {prediction.get('maintenance_type_used', 'treinado')})"
            )

    if predictions:
        lines.append("ML preditivo de manutencao: " + " | ".join(predictions))
    else:
        lines.append("ML preditivo de manutencao: sem previsao confiavel disponivel; nao invente prazos.")

    lines.append(
        "Regra de resposta: use estes dados como fonte quando forem relevantes; "
        "quando faltar dado cadastrado, diga isso claramente em vez de supor."
    )
    return "\n".join(lines)


def load_user_chat_context(cursor, user_id):
    user = get_user_by_id(cursor, user_id)
    if not user:
        return None

    cursor.execute(
        "SELECT id, tipo, marca, modelo, ano_fabricacao, ano_compra, quilometragem FROM veiculos WHERE user_id = %s",
        (user_id,)
    )
    veiculos = cursor.fetchall()
    if veiculos:
        user["lista_veiculos"] = veiculos
    try:
        user["chat_context"] = build_user_chat_data_context(cursor, user_id, veiculos)
    except Exception as exc:
        logger.warning("Nao foi possivel montar contexto do usuario para o chat: %s", exc)
    return user


def select_recent_chat_history(cursor, user_id, message, client_history, ignore_global_history):
    if is_generic_chat_message(message):
        return []
    if ignore_global_history or not user_id:
        return client_history
    return get_mysql_history(user_id, limit=3, cursor=cursor)


def build_chat_response(chat_id, session_id, message, resposta, videos, links, topic, attachments):
    return {
        "id": chat_id,
        "session_id": session_id or "",
        "mensagem_usuario": message,
        "resposta_ia": resposta,
        "created_at": datetime.now().isoformat(),
        "videos": videos,
        "links": links,
        "topic": topic or "",
        "attachments": attachments,
    }


def _is_effective_premium(user):
    """Premium válido considerando premium_expires_at (None = permanente)."""
    if not user or not user.get("is_premium"):
        return False
    expira = user.get("premium_expires_at")
    if expira is None:
        return True
    try:
        if isinstance(expira, str):
            expira = datetime.fromisoformat(expira.replace("Z", "+00:00"))
        return expira > datetime.now()
    except Exception:
        return True


def get_free_chat_usage_month(cursor, user_id):
    """Conta interações do usuário free no mês corrente (tabela chats)."""
    cursor.execute(
        """SELECT COUNT(*) AS cnt FROM chats
           WHERE user_id = %s AND created_at >= DATE_FORMAT(NOW(), '%%Y-%%m-01')""",
        (user_id,),
    )
    row = cursor.fetchone()
    return int((row or {}).get("cnt") or 0)


def _emit_free_limit_reached(user_id, used):
    """P0.3: emite ``free_limit_reached`` 1x por ciclo de limite (idempotente)."""
    try:
        if not has_prior_event("free_limit_reached", user_id=user_id, anonymous_id=None):
            record_analytics_event(
                "free_limit_reached",
                user_id=user_id,
                anonymous_id=None,
                path="/api/chat",
                metadata={"limit": FREE_MONTHLY_CHAT_LIMIT, "used": used},
            )
    except Exception as exc:
        logger.warning("Falha ao emitir free_limit_reached: %s", exc)


@pages_bp.route("/api/chat/history", methods=["GET"])
@jwt_required()
def get_chat_history():
    user_id = get_jwt_identity()
    after_id = parse_after_id(request.args.get("after_id"))
    limit = parse_history_limit(request.args.get("limit"))
    raw_session = request.args.get("session_id")
    try:
        with get_db() as (cursor, conn):
            user = get_user_by_id(cursor, user_id)
            if not user:
                return invalid_session_response()

            order_direction = "ASC" if after_id else "DESC"
            after_filter = "AND id > %s" if after_id else ""
            session_clause = ""
            session_params: list = []
            if raw_session is not None:
                if raw_session.strip().lower() == "null":
                    session_clause = "AND session_id IS NULL"
                else:
                    candidate = normalize_chat_session_id(raw_session)
                    if candidate is not None:
                        session_clause = "AND session_id = %s"
                        session_params.append(candidate)
            params = [user_id, *session_params]
            if after_id:
                params.append(after_id)
            params.append(limit)

            cursor.execute(
                f"""
                SELECT id, session_id, mensagem_usuario, resposta_ia, created_at, videos, links, topic, attachments
                FROM chats
                WHERE user_id = %s
                {session_clause}
                {after_filter}
                ORDER BY id {order_direction}
                LIMIT %s
                """,
                tuple(params)
            )
            rows = cursor.fetchall()
            if not after_id:
                rows = list(reversed(rows))

            chats = [serialize_chat_row(row) for row in rows]
            latest_id = max((chat["id"] for chat in chats), default=after_id)
            return jsonify(chats=chats, latest_id=latest_id), 200
    except Exception as e:
        logger.error(f"Erro no historico: {e}")
        return jsonify(error="Erro interno"), 500


@pages_bp.route("/api/chat/conversations", methods=["GET"])
@jwt_required()
def list_chat_conversations():
    user_id = get_jwt_identity()
    q = (request.args.get("q") or "").strip()
    try:
        with get_db() as (cursor, conn):
            user = get_user_by_id(cursor, user_id)
            if not user:
                return invalid_session_response()

            cursor.execute(
                """
                SELECT id, session_id, mensagem_usuario, resposta_ia, topic, created_at
                FROM chats
                WHERE user_id = %s
                ORDER BY id DESC
                """,
                (user_id,),
            )
            rows = cursor.fetchall()

        groups = {}
        order = []
        needle = q.lower()
        for row in rows:
            sid = row.get("session_id")
            key = sid if sid else "__null__"
            if key not in groups:
                groups[key] = {
                    "session_id": sid,
                    "topic": (row.get("topic") or "").strip(),
                    "preview": (row.get("mensagem_usuario") or "").strip(),
                    "updated_at": row.get("created_at"),
                    "count": 0,
                    "matches": False,
                }
                order.append(key)
            groups[key]["count"] += 1
            if needle:
                hay = " ".join([
                    row.get("mensagem_usuario") or "",
                    row.get("resposta_ia") or "",
                    row.get("topic") or "",
                ]).lower()
                if needle in hay:
                    groups[key]["matches"] = True

        conversations = []
        for key in order:
            g = groups[key]
            if needle and not g["matches"]:
                continue
            title = g["topic"] or g["preview"] or "Nova conversa"
            if key == "__null__" and not g["topic"]:
                title = "Consultoria geral"
            updated = g["updated_at"]
            conversations.append({
                "session_id": g["session_id"],
                "title": title[:80],
                "preview": g["preview"][:140],
                "updated_at": updated.isoformat() if hasattr(updated, "isoformat") else updated,
                "count": g["count"],
            })
        return jsonify(conversations=conversations), 200
    except Exception as e:
        logger.error(f"Erro ao listar conversas: {e}")
        return jsonify(error="Erro interno"), 500


@pages_bp.route("/api/chat/history/<int:chat_id>", methods=["DELETE"])
@jwt_required()
def delete_chat_history(chat_id):
    user_id = get_jwt_identity()
    try:
        with get_db() as (cursor, conn):
            user = get_user_by_id(cursor, user_id)
            if not user:
                return invalid_session_response()

            cursor.execute("DELETE FROM chats WHERE id = %s AND user_id = %s", (chat_id, user_id))
            if cursor.rowcount == 0:
                return jsonify(error="Chat nao encontrado"), 404

        return jsonify(success=True), 200
    except Exception as e:
        logger.error(f"Erro ao excluir chat: {e}")
        return jsonify(error="Erro ao excluir chat"), 500


@pages_bp.route("/api/chat/session/<session_id>", methods=["DELETE"])
@jwt_required()
def delete_chat_session(session_id):
    user_id = get_jwt_identity()
    try:
        with get_db() as (cursor, conn):
            user = get_user_by_id(cursor, user_id)
            if not user:
                return invalid_session_response()

            if session_id == "null":
                cursor.execute("DELETE FROM chats WHERE session_id IS NULL AND user_id = %s", (user_id,))
            else:
                cursor.execute("DELETE FROM chats WHERE session_id = %s AND user_id = %s", (session_id, user_id))

        return jsonify(success=True), 200
    except Exception as e:
        logger.error(f"Erro ao excluir sessao: {e}")
        return jsonify(error="Erro ao excluir sessao"), 500


@pages_bp.route("/api/chat/sync_guest", methods=["POST"])
@jwt_required()
def sync_guest_chat():
    user_id = get_jwt_identity()
    data = request.get_json() or {}
    chats = data.get("chats") or []
    
    if not chats:
        return jsonify(success=True), 200

    try:
        synced_count = 0
        with get_db() as (cursor, conn):
            for chat in chats:
                if not isinstance(chat, dict):
                    continue

                session_id = normalize_chat_session_id(chat.get("session_id"))
                mensagem_usuario = (chat.get("mensagem_usuario") or "").strip()
                resposta_ia = (chat.get("resposta_ia") or "").strip()
                if not mensagem_usuario and not resposta_ia:
                    continue

                created_at = parse_client_created_at(chat.get("created_at"))
                videos = parse_json_list(chat.get("videos"))
                links = parse_json_list(chat.get("links"))
                topic = (chat.get("topic") or "").strip()[:255]
                attachments = parse_json_list(chat.get("attachments"))

                if session_id:
                    cursor.execute(
                        """
                        SELECT id FROM chats
                        WHERE user_id = %s AND session_id = %s
                          AND mensagem_usuario = %s AND resposta_ia = %s
                        LIMIT 1
                        """,
                        (user_id, session_id, mensagem_usuario, resposta_ia)
                    )
                else:
                    cursor.execute(
                        """
                        SELECT id FROM chats
                        WHERE user_id = %s AND session_id IS NULL
                          AND mensagem_usuario = %s AND resposta_ia = %s
                        LIMIT 1
                        """,
                        (user_id, mensagem_usuario, resposta_ia)
                    )
                if cursor.fetchone():
                    continue

                cursor.execute(
                    """
                    INSERT INTO chats (user_id, session_id, mensagem_usuario, resposta_ia, created_at, videos, links, topic, attachments)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        user_id,
                        session_id,
                        mensagem_usuario,
                        resposta_ia,
                        created_at,
                        json.dumps(videos),
                        json.dumps(links),
                        topic,
                        json.dumps(attachments),
                    )
                )
                synced_count += 1
        return jsonify(success=True, synced=synced_count), 200
    except Exception as e:
        logger.error(f"Erro ao sincronizar chat de visitante: {e}")
        return jsonify(error="Erro interno ao sincronizar chat"), 500


@pages_bp.route("/api/chat", methods=["POST"])
@limiter.limit("20 per hour")
@limiter.limit("30 per hour", key_func=lambda: __import__("utils.rate_limit", fromlist=["chat_rate_key"]).chat_rate_key())
@limiter.limit("100 per day", key_func=lambda: __import__("utils.rate_limit", fromlist=["chat_rate_key"]).chat_rate_key())
@turnstile_or_auth(action="chat")
def chat():
    user_id = get_optional_user_id()
    raw = request.get_json(silent=True) or {}
    # P1: validação tipada (pydantic) com fallback para payload legado
    try:
        from schemas.chat import ChatInput as _ChatInput
        parsed = _ChatInput.model_validate(raw)
        data = raw
        msg = (parsed.message or "").strip()
        session_id = normalize_chat_session_id(parsed.session_id)
        img_b64 = parsed.image
        req_anonymous_id = (parsed.anonymous_id or "").strip()[:80] or None
        vehicle_id = parsed.vehicle_id
        user_lat = parsed.lat
        user_lng = parsed.lng
        client_history = normalize_client_history(
            [h.model_dump() if hasattr(h, "model_dump") else h for h in (parsed.client_history or [])]
        )
        ignore_global_history = bool(parsed.ignore_global_history)
        _guest_id_hint = (parsed.guest_id or "").strip() or None
    except Exception as _ve:
        from pydantic import ValidationError as _VE
        if isinstance(_ve, _VE):
            return jsonify(error="Payload inválido.", details=str(_ve)[:500]), 400
        data = raw
        msg = (data.get("message") or "").strip()
        session_id = normalize_chat_session_id(data.get("session_id"))
        img_b64 = data.get("image")
        req_anonymous_id = (data.get("anonymous_id") or "").strip()[:80] or None
        vehicle_id = data.get("vehicle_id")
        client_history = normalize_client_history(data.get("client_history"))
        ignore_global_history = bool(data.get("ignore_global_history"))
        user_lat = data.get("lat")
        user_lng = data.get("lng")
        if user_lat is not None:
            try: user_lat = float(user_lat)
            except (TypeError, ValueError): user_lat = None
        if user_lng is not None:
            try: user_lng = float(user_lng)
            except (TypeError, ValueError): user_lng = None
        _guest_id_hint = None
    try:
        attachment = parse_chat_attachment(data)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400

    if not msg and not img_b64 and not attachment:
        return jsonify(error="Envie uma mensagem ou anexe um arquivo para análise."), 400

    try:
        with get_db() as (cursor, conn):
            guest_messages_remaining = None
            if user_id:
                user = load_user_chat_context(cursor, user_id)
                if not user:
                    return invalid_session_response()
                # P0-1: free tem quota mensal; premium é ilimitado.
                if not _is_effective_premium(user):
                    used = get_free_chat_usage_month(cursor, user_id)
                    if used >= FREE_MONTHLY_CHAT_LIMIT:
                        # P0.3: instrumenta a chegada ao teto do plano gratuito
                        # (idempotente por usuário: 1 evento por ciclo de limite).
                        _emit_free_limit_reached(user_id, used)
                        return jsonify(
                            error="Você atingiu seu limite mensal de consultas no plano gratuito. Assine o Premium para consultas ilimitadas com a IA NOG.",
                            code="free_limit_reached",
                            limit=FREE_MONTHLY_CHAT_LIMIT,
                            used=used,
                        ), 403
            else:
                guest_id = normalize_guest_id((_guest_id_hint or data.get("guest_id")) or request.headers.get("X-AutoAssist-Guest-Id"))
                if not guest_id:
                    return jsonify(error="Identificação de visitante inválida. Recarregue a página e tente novamente."), 400

                guest_messages_remaining = reserve_guest_message(cursor, guest_id)
                if guest_messages_remaining is None:
                    return jsonify(
                        error="Você atingiu o limite de 5 mensagens gratuitas. Crie uma conta ou faça login para continuar.",
                        code="guest_limit_reached",
                        limit=GUEST_CHAT_LIMIT,
                    ), 403
                user = {"nome": "Visitante", "is_guest": True}

            historico_recente = select_recent_chat_history(
                cursor,
                user_id,
                msg,
                client_history,
                ignore_global_history,
            )

            reference_images = []
            if user_id and vehicle_id:
                reference_images = get_vehicle_reference_images(cursor, user_id, vehicle_id)

        if user_lat is not None and user_lng is not None:
            user["lat"] = user_lat
            user["lng"] = user_lng

        resposta, videos, links, topic = generate_assistant_payload(
            msg,
            user_id or 0,
            user,
            historico_recente,
            image_b64=img_b64,
            attachment=attachment,
            default_topic="Consultoria Geral",
            reference_images=reference_images,
        )

        stored_message = msg
        if not stored_message and attachment:
            stored_message = f"Arquivo anexado: {attachment['name']}"
        elif not stored_message and img_b64:
            stored_message = "Imagem anexada"

        attachments = attachment_metadata(attachment)
        chat_id = None
        if user_id:
            with get_db() as (cursor, conn):
                cursor.execute(
                    """
                    INSERT INTO chats (user_id, session_id, mensagem_usuario, resposta_ia, videos, links, topic, attachments)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        user_id,
                        session_id,
                        stored_message,
                        resposta,
                        json.dumps(videos),
                        json.dumps(links),
                        topic,
                        json.dumps(attachments),
                    )
                )
                chat_id = cursor.lastrowid
                if vehicle_id and user_id:
                    seed_b64 = img_b64
                    if not seed_b64 and attachment and attachment.get("kind") == "image":
                        seed_b64 = (
                            "data:" + attachment["mime_type"] + ";base64,"
                            + base64.b64encode(attachment["data"]).decode("ascii")
                        )
                    if seed_b64:
                        seed_vehicle_photo_if_missing(cursor, conn, user_id, vehicle_id, seed_b64)

        response_payload = dict(
            response=resposta,
            videos=videos,
            links=links,
            chat=build_chat_response(chat_id, session_id, stored_message, resposta, videos, links, topic, attachments),
        )
        if guest_messages_remaining is not None:
            response_payload["guest_messages_remaining"] = guest_messages_remaining
            response_payload["guest_limit"] = GUEST_CHAT_LIMIT

        # P0.2: instrumentação do funil de negócio (NOG / Raio-X).
        # Emite somente após a resposta ser gerada com sucesso (a análise
        # de imagem, se houver, já ocorreu dentro de generate_assistant_payload).
        _emit_usage_events(
            user_id=user_id,
            anonymous_id=req_anonymous_id if not user_id else None,
            is_raio=bool(img_b64) or bool(attachment and attachment.get("kind") in ("image", "binary")),
        )
        return jsonify(response_payload)
    except Exception as e:
        logger.error(f"Erro na rota /api/chat: {e}")
        return jsonify(error="Erro interno"), 500


@pages_bp.route("/api/voice", methods=["POST"])
@turnstile_or_auth(action="chat")
def handle_voice():
    user_id = get_optional_user_id()
    if 'audio' not in request.files:
        return jsonify(error="Nenhum áudio recebido"), 400

    audio_file = request.files['audio']
    img_b64 = request.form.get("image")
    session_id = normalize_chat_session_id(request.form.get("session_id"))
    attachment = None
    if request.form.get("attachment"):
        try:
            attachment = parse_chat_attachment({"attachment": json.loads(request.form.get("attachment"))})
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        except Exception:
            return jsonify(error="Arquivo anexado inválido."), 400

    ignore_global_history = (request.form.get("ignore_global_history") or "").lower() in ("1", "true", "yes")
    try:
        client_history = normalize_client_history(json.loads(request.form.get("client_history") or "[]"))
    except Exception:
        client_history = []

    try:
        # Converter o audio recebido para wav usando pydub (formato detectado automaticamente)
        audio_segment = AudioSegment.from_file(audio_file)
        wav_io = io.BytesIO()
        audio_segment.export(wav_io, format="wav")
        wav_io.seek(0)

        # Reconhecimento de fala
        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_io) as source:
            audio_data = recognizer.record(source)

        text = recognizer.recognize_google(audio_data, language="pt-BR")

        with get_db() as (cursor, conn):
            guest_messages_remaining = None
            if user_id:
                user = load_user_chat_context(cursor, user_id)
                if not user:
                    return invalid_session_response()
                # P0-1: free tem quota mensal; premium é ilimitado.
                if not _is_effective_premium(user):
                    used = get_free_chat_usage_month(cursor, user_id)
                    if used >= FREE_MONTHLY_CHAT_LIMIT:
                        # P0.3: instrumenta a chegada ao teto do plano gratuito
                        # (idempotente por usuário: 1 evento por ciclo de limite).
                        _emit_free_limit_reached(user_id, used)
                        return jsonify(
                            error="Você atingiu seu limite mensal de consultas no plano gratuito. Assine o Premium para consultas ilimitadas com a IA NOG.",
                            code="free_limit_reached",
                            limit=FREE_MONTHLY_CHAT_LIMIT,
                            used=used,
                        ), 403
            else:
                guest_id = normalize_guest_id(request.form.get("guest_id") or request.headers.get("X-AutoAssist-Guest-Id"))
                if not guest_id:
                    return jsonify(error="Identificação de visitante inválida. Recarregue a página e tente novamente."), 400

                guest_messages_remaining = reserve_guest_message(cursor, guest_id)
                if guest_messages_remaining is None:
                    return jsonify(
                        error="Você atingiu o limite de 5 mensagens gratuitas. Crie uma conta ou faça login para continuar.",
                        code="guest_limit_reached",
                        limit=GUEST_CHAT_LIMIT,
                    ), 403
                user = {"nome": "Visitante", "is_guest": True}

            historico_recente = select_recent_chat_history(
                cursor,
                user_id,
                text,
                client_history,
                ignore_global_history,
            )

        voice_lat = request.form.get("lat")
        voice_lng = request.form.get("lng")
        if voice_lat is not None:
            try: user["lat"] = float(voice_lat)
            except (TypeError, ValueError): pass
        if voice_lng is not None:
            try: user["lng"] = float(voice_lng)
            except (TypeError, ValueError): pass

        resposta, videos, links, topic = generate_assistant_payload(
            text,
            user_id or 0,
            user,
            historico_recente,
            image_b64=img_b64,
            attachment=attachment,
            default_topic="Consultoria por Voz",
        )

        attachments = attachment_metadata(attachment)
        chat_id = None
        if user_id:
            with get_db() as (cursor, conn):
                cursor.execute(
                    """
                    INSERT INTO chats (user_id, session_id, mensagem_usuario, resposta_ia, videos, links, topic, attachments)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        user_id,
                        session_id,
                        text,
                        resposta,
                        json.dumps(videos),
                        json.dumps(links),
                        topic,
                        json.dumps(attachments),
                    )
                )
                chat_id = cursor.lastrowid

        response_payload = dict(
            text=text,
            response=resposta,
            videos=videos,
            links=links,
            chat=build_chat_response(chat_id, session_id, text, resposta, videos, links, topic, attachments),
        )
        if guest_messages_remaining is not None:
            response_payload["guest_messages_remaining"] = guest_messages_remaining
            response_payload["guest_limit"] = GUEST_CHAT_LIMIT

        # P0.2: instrumentação do funil de negócio (NOG / Raio-X) via voz.
        _emit_usage_events(
            user_id=user_id,
            anonymous_id=(request.form.get("anonymous_id") or "").strip()[:80] or None
            if not user_id else None,
            is_raio=bool(img_b64) or bool(attachment and attachment.get("kind") in ("image", "binary")),
        )
        return jsonify(response_payload)

    except sr.UnknownValueError:
        return jsonify(error="Não entendi o que foi falado. Pode repetir?"), 400
    except sr.RequestError as e:
        logger.error(f"Erro de serviço SR: {e}")
        return jsonify(error="Erro no serviço de voz."), 500
    except Exception as e:
        logger.error(f"Erro na rota /api/voice: {e}")
        return jsonify(error="Erro interno ao processar voz"), 500

