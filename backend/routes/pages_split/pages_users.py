"""Split de routes/pages.py — módulo pages_users (P1).

Carregado via exec() em routes/pages.py compartilhando os mesmos globals
(imports, pages_bp, constantes, logger). Não importar diretamente.
"""

def get_dashboard_url() -> str:
    # Return URL to the legacy HTML dashboard page
    base = request.host_url.rstrip('/')
    return f"{base}/dashboard.html"


def get_user_by_id(cursor, user_id):
    cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    return cursor.fetchone()


def invalid_session_response():
    return jsonify(error=INVALID_SESSION_ERROR), 401


def ensure_premium_user(user):
    if not user:
        return invalid_session_response()
    if bool(user.get("is_premium")):
        return None
    return jsonify(error=PREMIUM_ONLY_ERROR), 403


def ensure_maintenance_access(user, cursor):
    """P1-1: free pode registrar até FREE_MAINTENANCE_LIMIT manutenções; premium ilimitado.
    Listagem é liberada para todos (free vê seus próprios registros)."""
    if not user:
        return invalid_session_response()
    if bool(user.get("is_premium")):
        return None
    user_id = user.get("id")
    cursor.execute("SELECT COUNT(*) AS cnt FROM maintenance_history WHERE user_id = %s", (user_id,))
    row = cursor.fetchone()
    count = int((row or {}).get("cnt") or 0)
    if count >= FREE_MAINTENANCE_LIMIT:
        return jsonify(
            error=f"O plano gratuito permite ate {FREE_MAINTENANCE_LIMIT} registros de manutencao. Assine o Premium para historico ilimitado.",
            code="free_maintenance_limit_reached",
            limit=FREE_MAINTENANCE_LIMIT,
            used=count,
        ), 403
    return None


@pages_bp.route("/api/user", methods=["GET"])
@jwt_required()
def get_user():
    user_id = get_jwt_identity()
    with get_db() as (cursor, conn):
        cursor.execute("""
            SELECT id, nome, email, is_premium, created_at, possui_veiculo,
                   veiculo_marca, veiculo_modelo, veiculo_ano_fabricacao,
                   veiculo_ano_compra, veiculo_tipo, veiculo_quilometragem, is_two_factor_enabled,
                   maintenance_email_enabled, maintenance_email_last_sent, uf
            FROM users WHERE id = %s
        """, (user_id,))
        user = cursor.fetchone()
        if not user:
            return invalid_session_response()
        user["maintenance_email_last_sent"] = serialize_datetime_field(user.get("maintenance_email_last_sent"))

        cursor.execute("SELECT COUNT(DISTINCT session_id) AS total FROM chats WHERE user_id = %s", (user_id,))
        total = cursor.fetchone()

        try:
            cursor.execute("SELECT id, tipo, marca, modelo, ano_fabricacao, ano_compra, quilometragem, fipe_valor, fipe_mes_referencia, foto_base64, foto_url, foto_storage_key, foto_mime, foto_storage FROM veiculos WHERE user_id = %s", (user_id,))
        except Exception:
            cursor.execute("SELECT id, tipo, marca, modelo, ano_fabricacao, ano_compra, quilometragem, fipe_valor, fipe_mes_referencia, foto_base64 FROM veiculos WHERE user_id = %s", (user_id,))
        veiculos = cursor.fetchall()

        for v in veiculos:
            if isinstance(v.get("fipe_valor"), Decimal):
                v["fipe_valor"] = float(v["fipe_valor"])
            _enrich_veiculo_foto(v)

        return jsonify({
            **user,
            "trial_expired": is_trial_expired(user),
            "trial_days_remaining": get_trial_days_remaining(user),
            "is_premium": bool(user.get("is_premium")),
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
            if not user:
                return invalid_session_response()

            cursor.execute("SELECT COUNT(DISTINCT session_id) AS total FROM chats WHERE user_id = %s", (user_id,))
            total = cursor.fetchone()

            return jsonify({
                **user,
                "trial_expired": is_trial_expired(user),
                "trial_days_remaining": get_trial_days_remaining(user),
                "is_premium": bool(user.get("is_premium")),
                "total_consultas": int(total["total"]),
                "success": True
            }), 200
    except Exception as e:
        logger.error(f"❌ Erro ao atualizar perfil: {e}")
        return jsonify(error="Erro ao atualizar perfil"), 500


@pages_bp.route("/api/user/location", methods=["POST"])
@jwt_required()
def update_user_location():
    """Salva a localização (UF) do usuário para notificações regionais de eventos.

    Recebe {lat, lng} (geolocalização do navegador) - a UF é inferida por
    reverse geocoding (Nominatim) e cacheadas por ~1km. Também aceita {uf}
    diretamente e {uf: ""} para limpar a localização.
    """
    user_id = get_jwt_identity()
    data = request.get_json() or {}
    uf = (data.get("uf") or "").strip().upper()

    if not uf and data.get("lat") is not None and data.get("lng") is not None:
        try:
            from utils.geocode import reverse_geocode_uf
            uf = reverse_geocode_uf(data["lat"], data["lng"]) or ""
        except Exception as e:
            logger.warning("Falha ao inferir UF pela localização: %s", e)
            uf = ""

    if uf and (len(uf) != 2 or not uf.isalpha()):
        return jsonify(error="UF inválida"), 400

    try:
        with get_db() as (cursor, conn):
            cursor.execute(
                "UPDATE users SET uf = %s WHERE id = %s",
                (uf or None, user_id),
            )
            conn.commit()
        return jsonify(success=True, uf=uf or None), 200
    except Exception as e:
        logger.error(f"❌ Erro ao salvar localização do usuário: {e}")
        return jsonify(error="Erro ao salvar localização"), 500


@pages_bp.route("/api/user", methods=["DELETE"])
@jwt_required()
def delete_user():
    user_id = get_jwt_identity()
    try:
        with get_db() as (cursor, conn):
            cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
        return jsonify(success=True), 200
    except Exception as e:
        logger.error(f"Erro ao excluir conta: {e}")
        return jsonify(error="Erro ao excluir conta"), 500

