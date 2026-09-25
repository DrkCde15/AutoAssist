"""Split de routes/pages.py — módulo pages_vehicles (P1).

Carregado via exec() em routes/pages.py compartilhando os mesmos globals
(imports, pages_bp, constantes, logger). Não importar diretamente.
"""

from typing import TYPE_CHECKING
if TYPE_CHECKING:  # noqa: F401 — nomes providos em runtime pelos globals de routes/pages.py (exec)
    from decimal import Decimal
    import base64
    from routes.database import get_db
    from flask_jwt_extended import get_jwt_identity
    import json
    from flask import jsonify
    from flask_jwt_extended import jwt_required
    from flask import request
    from .pages_maintenance import _enqueue_alert_email, _invalidate_dashboard_cache_for_user, send_maintenance_alert_email_for_user
    from .pages_modpassport import _calcular_detalhe
    from .pages_users import get_user_by_id
    from ..pages import CRITICAL_MAINTENANCE_STATUSES, FIPE_AJUSTADA_DISCLAIMER, logger, pages_bp

def _enrich_veiculo_foto(v):
    """P2: garante foto_url/foto_mime no payload mesmo em bancos antigos."""
    try:
        if not isinstance(v, dict):
            return v
        if v.get("foto_url"):
            return v
        key = v.get("foto_storage_key")
        if key and not v.get("foto_url"):
            try:
                from services.vehicle_photo_storage import photo_url_for
                v["foto_url"] = photo_url_for(int(v.get("id") or 0), key)
            except Exception:
                pass
        return v
    except Exception:
        return v


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
                INSERT INTO veiculos (user_id, tipo, marca, modelo, ano_fabricacao, ano_compra, quilometragem)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (user_id, data.get("tipo"), data.get("marca"), data.get("modelo"), ano_fab, ano_compra, data.get("quilometragem")))
            v_id = cursor.lastrowid
            cursor.execute("UPDATE users SET possui_veiculo = TRUE WHERE id = %s", (user_id,))

            # Popula o valor FIPE na criacao (assincrono via RQ, com fallback sincrono).
            # Garante que o Patrimonio e o card de FIPE tenham base numerica.
            try:
                from routes.dashboard import _refresh_fipe
                _refresh_fipe(v_id, data.get("tipo"), data.get("marca"),
                             data.get("modelo"), ano_fab)
            except Exception as fipe_err:
                logger.warning(f"Falha ao agendar refresh FIPE na criacao: {fipe_err}")

            # Gatilho imediato de e-mail se houver algo crítico
            try:
                user_row = get_user_by_id(cursor, user_id)
                if user_row:
                    send_maintenance_alert_email_for_user(
                        cursor,
                        user_row,
                        force=False,
                        status_codes=CRITICAL_MAINTENANCE_STATUSES,
                        transition_only=True,
                    )
            except Exception as email_err:
                logger.warning(f"Falha no gatilho imediato de email: {email_err}")

            _invalidate_dashboard_cache_for_user(user_id)
            try:
                from routes.notifications import create_notification
                from routes.push import send_push_notification
                create_notification(
                    user_id,
                    "Veiculo adicionado!",
                    "Crie o Mod Passport para acompanhar o valor estimado e o historico do seu carro pela IA.",
                    type="ativo",
                    action_url="dashboard.html",
                )
                send_push_notification(
                    user_id,
                    "Bem-vindo ao AutoAssist!",
                    "Toque para criar o Mod Passport do seu veiculo.",
                    data={"url": "dashboard.html"},
                )
            except Exception as act_err:
                logger.warning("Falha na notificacao de ativacao: %s", act_err)
            return jsonify(success=True, id=v_id), 201
    except Exception as e:
        logger.error(f"Erro ao adicionar veiculo: {e}")
        return jsonify(error="Erro interno ao adicionar veículo"), 500


@pages_bp.route("/api/veiculos", methods=["GET"])
@jwt_required()
def list_veiculos():
    user_id = get_jwt_identity()
    try:
        with get_db() as (cursor, conn):
            try:
                cursor.execute(
                    """
                    SELECT id, tipo, marca, modelo, ano_fabricacao, ano_compra, quilometragem,
                           fipe_valor, fipe_mes_referencia, modificacoes, fipe_ajustada, foto_base64,
                           foto_url, foto_storage_key, foto_mime, foto_storage
                    FROM veiculos
                    WHERE user_id = %s
                    ORDER BY created_at DESC, id DESC
                    """,
                    (user_id,)
                )
            except Exception:
                cursor.execute(
                    """
                    SELECT id, tipo, marca, modelo, ano_fabricacao, ano_compra, quilometragem,
                           fipe_valor, fipe_mes_referencia, modificacoes, fipe_ajustada, foto_base64
                    FROM veiculos
                    WHERE user_id = %s
                    ORDER BY created_at DESC, id DESC
                    """,
                    (user_id,)
                )
            veiculos = cursor.fetchall()
            for v in veiculos:
                _enrich_veiculo_foto(v)
                if isinstance(v.get("fipe_valor"), Decimal):
                    v["fipe_valor"] = float(v["fipe_valor"])
                if v.get("fipe_ajustada") is not None and isinstance(v.get("fipe_ajustada"), Decimal):
                    v["fipe_ajustada"] = float(v["fipe_ajustada"])
                # Fundamenta o valor estimado com precos de mercado reais (best-effort).
                mods = v.get("modificacoes")
                if isinstance(mods, str):
                    try:
                        mods = json.loads(mods)
                    except (ValueError, TypeError):
                        mods = []
                if v.get("fipe_valor") or mods:
                    mercado = None
                    if mods:
                        try:
                            from services import web_scraping as _ws
                            mkt = _ws.get_market_price_estimate(
                                v.get("marca"), v.get("modelo"), v.get("ano_fabricacao")
                            )
                            if mkt:
                                mercado = mkt[0]
                        except Exception as mkt_err:
                            logger.debug("enriquecimento de mercado falhou: %s", mkt_err)
                    det = _calcular_detalhe(v.get("fipe_valor"), mods, mercado=mercado)
                    v["fipe_ajustada"] = det["valor"]
                    v["fipe_ajustada_fonte"] = det["base_fonte"]
                    v["fipe_ajustada_metodo"] = det["detalhe"]
                    v["fipe_ajustada_aviso"] = (
                        FIPE_AJUSTADA_DISCLAIMER if (mods or mercado) else None
                    )
            return jsonify(veiculos=veiculos), 200
    except Exception as e:
        logger.error(f"Erro ao listar veiculos: {e}")
        return jsonify(error="Erro ao listar veiculos"), 500


@pages_bp.route("/api/veiculos/<int:v_id>/foto", methods=["POST"])
@jwt_required()
def upload_veiculo_foto(v_id):
    """Salva (ou remove) a foto do veículo. Recebe base64 em ``foto`` ou multipart ``file``.

    P2: salva no storage externo (local/S3) e grava ``foto_url``/``foto_storage_key``.
    Mantém ``foto_base64`` legado por compatibilidade (dual-read no frontend).
    Enviar ``foto`` vazio/nulo limpa a foto atual.
    """
    user_id = get_jwt_identity()
    # Multipart (novo): campo "file"
    raw_bytes = None
    if request.files and "file" in request.files:
        try:
            from services.vehicle_photo_storage import parse_data_url, get_storage, photo_url_for
            import base64 as _b64
            f = request.files["file"]
            raw_bytes = f.read()
            if not raw_bytes:
                return jsonify(error="Arquivo vazio"), 400
            # Reusa validação via base64 round-trip
            data, mime = parse_data_url("data:" + (f.mimetype or "image/jpeg") + ";base64," + _b64.b64encode(raw_bytes).decode("ascii"))
            raw_bytes = data
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        except Exception:
            return jsonify(error="Falha ao ler arquivo"), 400
        foto = None
    else:
        data = request.get_json(silent=True) or {}
        foto = data.get("foto")
    try:
        with get_db() as (cursor, conn):
            # Garante colunas P2 em bancos antigos (best-effort)
            try:
                cursor.execute("SHOW COLUMNS FROM veiculos")
                _cols = {r["Field"] for r in cursor.fetchall()}
                for _col, _dtype in (
                    ("foto_url", "VARCHAR(500) NULL"),
                    ("foto_storage_key", "VARCHAR(500) NULL"),
                    ("foto_mime", "VARCHAR(50) NULL"),
                    ("foto_storage", "VARCHAR(20) NULL"),
                ):
                    if _col not in _cols:
                        try:
                            cursor.execute(f"ALTER TABLE veiculos ADD COLUMN {_col} {_dtype}")
                        except Exception:
                            pass
            except Exception:
                pass
            cursor.execute("SELECT id, foto_storage_key FROM veiculos WHERE id = %s AND user_id = %s", (v_id, user_id))
            row = cursor.fetchone()
            if not row:
                return jsonify(error="Veículo não encontrado"), 404

            if raw_bytes is None and not foto:
                # Remove foto (storage + legado)
                try:
                    from services.vehicle_photo_storage import get_storage
                    old_key = (row.get("foto_storage_key") if isinstance(row, dict) else None)
                    if old_key:
                        get_storage().delete(old_key)
                except Exception:
                    pass
                try:
                    cursor.execute(
                        "UPDATE veiculos SET foto_base64 = NULL, foto_url = NULL, foto_storage_key = NULL, foto_mime = NULL, foto_storage = NULL WHERE id = %s AND user_id = %s",
                        (v_id, user_id),
                    )
                except Exception:
                    cursor.execute("UPDATE veiculos SET foto_base64 = NULL WHERE id = %s AND user_id = %s", (v_id, user_id))
                conn.commit()
                _invalidate_dashboard_cache_for_user(user_id)
                return jsonify(success=True, foto_base64=None, foto_url=None), 200

            from services.vehicle_photo_storage import parse_data_url, get_storage, photo_url_for
            import base64 as _b64mod
            import os as _os

            if raw_bytes is None:
                if isinstance(foto, str) and foto.startswith("data:"):
                    raw_value = foto
                elif isinstance(foto, str):
                    raw_value = foto
                else:
                    return jsonify(error="Formato de imagem inválido"), 400
                try:
                    img_bytes, mime = parse_data_url(raw_value)
                except ValueError as exc:
                    return jsonify(error=str(exc)), 400
                # foto legado (base64 puro, sem prefixo) para dual-read
                foto_b64 = _b64mod.b64encode(img_bytes).decode("ascii")
            else:
                img_bytes = raw_bytes
                from services.vehicle_photo_storage import sniff_mime
                mime = sniff_mime(img_bytes) or "image/jpeg"
                foto_b64 = _b64mod.b64encode(img_bytes).decode("ascii")

            # Remove foto anterior do storage
            try:
                old_key = (row.get("foto_storage_key") if isinstance(row, dict) else None)
                if old_key:
                    get_storage().delete(old_key)
            except Exception:
                pass

            store = get_storage()
            backend_name = (_os.getenv("VEHICLE_PHOTO_BACKEND") or "local").strip().lower()
            try:
                storage_key = store.save(int(user_id), int(v_id), img_bytes, mime)
            except Exception as exc:
                logger.error("Falha no storage de foto, fallback DB: %s", exc)
                storage_key = None
            foto_url = photo_url_for(int(v_id), storage_key) if storage_key else None
            try:
                cursor.execute(
                    "UPDATE veiculos SET foto_base64 = %s, foto_url = %s, foto_storage_key = %s, foto_mime = %s, foto_storage = %s WHERE id = %s AND user_id = %s",
                    (foto_b64, foto_url, storage_key, mime, backend_name if storage_key else None, v_id, user_id),
                )
            except Exception:
                # Banco antigo sem colunas P2
                cursor.execute("UPDATE veiculos SET foto_base64 = %s WHERE id = %s AND user_id = %s", (foto_b64, v_id, user_id))
                foto_url = None
                storage_key = None
            conn.commit()
            _invalidate_dashboard_cache_for_user(user_id)
            return jsonify(success=True, foto_base64=foto_b64, foto_url=foto_url, foto_mime=mime), 200
    except Exception as e:
        logger.error(f"Erro ao salvar foto do veiculo: {e}")
        return jsonify(error="Erro ao salvar foto do veículo"), 500


@pages_bp.route("/api/veiculos/<int:v_id>/foto/raw", methods=["GET"])
@jwt_required()
def serve_veiculo_foto(v_id):
    """Serve a foto do veículo (P2: storage externo; fallback foto_base64 legado)."""
    from flask import Response
    import base64 as _b64mod
    user_id = get_jwt_identity()
    try:
        with get_db() as (cursor, conn):
            try:
                cursor.execute(
                    "SELECT foto_storage_key, foto_mime, foto_base64 FROM veiculos WHERE id = %s AND user_id = %s",
                    (v_id, user_id),
                )
            except Exception:
                cursor.execute("SELECT foto_base64 FROM veiculos WHERE id = %s AND user_id = %s", (v_id, user_id))
            row = cursor.fetchone()
            if not row:
                return jsonify(error="Veículo não encontrado"), 404
            key = row.get("foto_storage_key") if isinstance(row, dict) else None
            if key:
                from services.vehicle_photo_storage import get_storage
                found = get_storage().get(key)
                if found:
                    data, mime = found
                    return Response(data, mimetype=mime or row.get("foto_mime") or "image/jpeg")
            b64 = row.get("foto_base64") if isinstance(row, dict) else None
            if not b64:
                return jsonify(error="Veículo sem foto"), 404
            if isinstance(b64, str) and b64.startswith("data:"):
                _, _, b64 = b64.partition(",")
            try:
                data = _b64mod.b64decode(b64, validate=True)
            except Exception:
                return jsonify(error="Foto corrompida"), 500
            from services.vehicle_photo_storage import sniff_mime
            return Response(data, mimetype=sniff_mime(data) or "image/jpeg")
    except Exception as exc:
        logger.error("Erro ao servir foto do veículo: %s", exc)
        return jsonify(error="Erro ao servir foto"), 500


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
                SET tipo = %s, marca = %s, modelo = %s, ano_fabricacao = %s, ano_compra = %s, quilometragem = %s
                WHERE id = %s AND user_id = %s
            """, (data.get("tipo"), data.get("marca"), data.get("modelo"), ano_fab, ano_compra, data.get("quilometragem"), v_id, user_id))

            # Gatilho imediato de e-mail em segundo plano (Não trava o usuário)
            try:
                user_row = get_user_by_id(cursor, user_id)
                if user_row:
                    _enqueue_alert_email(user_row)
            except Exception as email_err:
                logger.warning(f"Erro ao iniciar thread de email: {email_err}")

            _invalidate_dashboard_cache_for_user(user_id)
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

            _invalidate_dashboard_cache_for_user(user_id)
            return jsonify(success=True), 200
    except Exception as e:
        logger.error(f"Erro ao excluir veiculo: {e}")
        return jsonify(error="Erro interno"), 500


def get_vehicle_reference_images(cursor, user_id, vehicle_id):
    """Fotos de referência do veículo para diagnóstico visual assistido (memória visual)."""
    try:
        vid = int(vehicle_id)
    except (TypeError, ValueError):
        return []
    if vid <= 0:
        return []
    try:
        cursor.execute(
            "SELECT foto_base64 FROM veiculos WHERE id=%s AND user_id=%s",
            (vid, user_id),
        )
        row = cursor.fetchone()
    except Exception as exc:
        logger.warning("Falha ao buscar foto de referência do veículo: %s", exc)
        return []
    if not row:
        return []
    foto = row.get("foto_base64")
    if foto and str(foto).strip():
        return [_foto_to_data_url(str(foto).strip()) or str(foto).strip()]
    return []


def _foto_to_data_url(foto):
    """Converte foto armazenada (data URI ou base64 puro) em data URI para a API de visão."""
    if not foto:
        return None
    if foto.startswith("data:"):
        return foto
    try:
        amostra = base64.b64decode(foto[:64])
    except Exception:
        return None
    if amostra[:3] == b"\xff\xd8\xff":
        mime = "image/jpeg"
    elif amostra[:4] == b"\x89PNG":
        mime = "image/png"
    elif amostra[:3] == b"GIF":
        mime = "image/gif"
    elif amostra[:4] == b"RIFF" and len(amostra) >= 12 and amostra[8:12] == b"WEBP":
        mime = "image/webp"
    else:
        mime = "image/jpeg"
    return f"data:{mime};base64,{foto}"


def seed_vehicle_photo_if_missing(cursor, conn, user_id, vehicle_id, image_b64):
    """Se o veículo ainda não tem foto, usa a imagem do diagnóstico como baseline de memória."""
    try:
        vid = int(vehicle_id)
    except (TypeError, ValueError):
        return
    if vid <= 0 or not image_b64:
        return
    try:
        cursor.execute(
            "UPDATE veiculos SET foto_base64=%s WHERE id=%s AND user_id=%s AND foto_base64 IS NULL",
            (image_b64, vid, user_id),
        )
        conn.commit()
        if cursor.rowcount:
            _invalidate_dashboard_cache_for_user(user_id)
    except Exception as exc:
        logger.warning("Falha ao semear foto do veículo: %s", exc)

