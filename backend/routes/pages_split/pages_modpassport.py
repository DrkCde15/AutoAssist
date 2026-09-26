"""Split de routes/pages.py — módulo pages_modpassport (P1).

Carregado via exec() em routes/pages.py compartilhando os mesmos globals
(imports, pages_bp, constantes, logger). Não importar diretamente.
"""

from typing import TYPE_CHECKING
if TYPE_CHECKING:  # noqa: F401 — nomes providos em runtime pelos globals de routes/pages.py (exec)
    from decimal import Decimal
    from datetime import datetime
    from routes.database import get_db
    from flask_jwt_extended import get_jwt_identity
    import io
    import json
    from flask import jsonify
    from flask_jwt_extended import jwt_required
    import re
    from flask import request
    from flask import send_file
    import uuid
    from .pages_maintenance import _invalidate_dashboard_cache_for_user
    from ..pages import FIPE_AJUSTADA_DISCLAIMER, _MOD_FIPE_PCT, _MOD_FIPE_PCT_MAX, logger, pages_bp

def _parse_fipe_valor(valor):
    """Extrai valor numerico (float) de uma string FIPE ('R$ 45.000,00')."""
    if valor is None:
        return 0.0
    if isinstance(valor, (int, float)):
        return float(valor)
    nums = re.findall(r"\d+[\.,]?\d*", str(valor).replace(".", "").replace(",", "."))
    for n in nums:
        try:
            return float(n)
        except ValueError:
            continue
    return 0.0


def _calcular_detalhe(base_valor, modificacoes, mercado=None):
    """Calcula o valor estimado de mercado de forma transparente e fundamentada.

    - A base e a Tabela FIPE (referencia oficial de mercado) OU a mediana de
      anuncios reais quando disponivel e coerente (ratio 0.4x-2.5x da FIPE).
    - O ajuste por modificacoes e uma estimativa conservadora e exposta
      (cada categoria contribui com seu peso, ate o teto).

    Retorna dict com valor, base usada, fonte, pct, extra e o detalhe por mod.
    """
    fipe_base = _parse_fipe_valor(base_valor)
    base = fipe_base
    fonte = "Tabela FIPE (referencia oficial de mercado)"
    if mercado and isinstance(mercado, (int, float)) and mercado > 0:
        if fipe_base > 0:
            ratio = mercado / fipe_base
            if 0.4 <= ratio <= 2.5:
                base = float(mercado)
                fonte = "Preco medio de anuncios reais (Mercado Livre)"
        else:
            base = float(mercado)
            fonte = "Preco medio de anuncios reais (Mercado Livre)"

    pct_total = 0.0
    extra_abs = 0.0
    detalhe = []
    for m in (modificacoes or []):
        cat = (m.get("categoria") or "outros").lower()
        p = _MOD_FIPE_PCT.get(cat, _MOD_FIPE_PCT["outros"])
        pct_total += p
        contrib_abs = 0.0
        v = m.get("valor")
        if v:
            try:
                contrib_abs = float(v)
                extra_abs += contrib_abs
            except (TypeError, ValueError):
                pass
        detalhe.append({"categoria": cat, "pct": p, "valor_informado": contrib_abs})

    pct_total = min(pct_total, _MOD_FIPE_PCT_MAX)
    ajustado = base * (1 + pct_total) + extra_abs
    valor_str = "R$ {:,.2f}".format(ajustado).replace(",", "X").replace(".", ",").replace("X", ".")
    return {
        "valor": valor_str,
        "base": base,
        "base_fonte": fonte,
        "pct": round(pct_total, 4),
        "extra_abs": round(extra_abs, 2),
        "detalhe": detalhe,
    }


def calcular_fipe_ajustada(base_valor, modificacoes, mercado=None):
    """Calcula o valor estimado de mercado por modificacoes (Mod Passport).

    Mantem a assinatura (valor_str, pct, extra) para retrocompatibilidade.
    'mercado' opcional = mediana de anuncios reais para fundamentar a base.
    """
    d = _calcular_detalhe(base_valor, modificacoes, mercado=mercado)
    return (d["valor"], d["pct"], d["extra_abs"])


def _salvar_mod_passport_version(cursor, veiculo_id, user_id, modificacoes, fipe_valor, fipe_ajustada):
    """Persiste um snapshot do Mod Passport para dar continuidade/historico (lock-in de dados)."""
    try:
        cursor.execute(
            """INSERT INTO mod_passport_versions
               (veiculo_id, user_id, snapshot, fipe_valor, fipe_ajustada, valor_estimado, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, NOW())""",
            (veiculo_id, user_id, json.dumps(modificacoes or [], ensure_ascii=False),
             fipe_valor, fipe_ajustada, fipe_ajustada),
        )
    except Exception as e:
        logger.warning("Falha ao versionar Mod Passport: %s", e)


def _l1(value):
    return str(value).encode("latin-1", "ignore").decode("latin-1")


def _build_modpassport_pdf(veiculo, snapshot, valor_estimado):
    """PDF do Mod Passport (ficha tecnica viva do veiculo)."""
    from fpdf import FPDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 15)
    pdf.set_text_color(59, 130, 246)
    pdf.cell(0, 10, _l1("AutoAssist IA - Mod Passport"), 0, 1, "C")
    pdf.ln(4)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 8, _l1("Veiculo:"), 0, 1)
    pdf.set_font("Arial", "", 11)
    nome = "{} {} ({})".format(
        veiculo.get("marca") or "", veiculo.get("modelo") or "", veiculo.get("ano_fabricacao") or ""
    )
    pdf.cell(0, 7, _l1(nome), 0, 1)
    pdf.cell(0, 7, _l1("Valor FIPE: {}".format(veiculo.get("fipe_valor") or "n/a")), 0, 1)
    pdf.cell(0, 7, _l1("Valor estimado (c/ mods): {}".format(valor_estimado or "n/a")), 0, 1)
    pdf.ln(3)
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 8, _l1("Modificacoes registradas:"), 0, 1)
    pdf.set_font("Arial", "", 10)
    mods = snapshot or []
    if not mods:
        pdf.cell(0, 6, _l1("(nenhuma)"), 0, 1)
    for m in mods:
        cat = m.get("categoria") or "outros"
        desc = m.get("descricao") or m.get("desc") or ""
        val = m.get("valor")
        linha = "- {}".format(cat)
        if desc:
            linha += ": {}".format(desc)
        if val:
            linha += " (R$ {})".format(val)
        pdf.multi_cell(0, 6, _l1(linha))
    pdf.ln(8)
    pdf.set_font("Arial", "I", 9)
    pdf.set_text_color(200, 50, 50)
    pdf.multi_cell(0, 5, _l1("AVISO: Mod Passport e uma estimativa gerada por IA. Nao substitui vistoria ou avaliacao profissional."))
    return pdf.output(dest="S").encode("latin-1")


def _require_mod_passport(cursor, user_id):
    """Exige premium ativo para o recurso Mod Passport."""
    cursor.execute("SELECT is_premium, premium_expires_at FROM users WHERE id = %s", (user_id,))
    row = cursor.fetchone()
    if not row or not row.get("is_premium"):
        return False, (jsonify(error="Recurso exclusivo Premium."), 403)
    expira = row.get("premium_expires_at")
    if expira is not None:
        try:
            if isinstance(expira, str):
                expira = datetime.fromisoformat(expira.replace("Z", "+00:00"))
            if expira < datetime.now():
                return False, (jsonify(error="Premium expirado. Renove para usar o Mod Passport."), 403)
        except Exception:
            pass
    return True, None


@pages_bp.route("/api/veiculos/<int:v_id>/modificacoes", methods=["POST"])
@jwt_required()
def set_veiculo_modificacoes(v_id):
    user_id = get_jwt_identity()
    data = request.get_json(silent=True) or {}
    modificacoes = data.get("modificacoes")
    if not isinstance(modificacoes, list):
        return jsonify(error="modificacoes deve ser uma lista."), 400
    try:
        with get_db() as (cursor, conn):
            ok, err = _require_mod_passport(cursor, user_id)
            if not ok:
                return err
            cursor.execute(
                "SELECT id, fipe_valor FROM veiculos WHERE id = %s AND user_id = %s",
                (v_id, user_id),
            )
            veh = cursor.fetchone()
            if not veh:
                return jsonify(error="Veiculo nao encontrado"), 404
            valor_ajustado, pct, extra = calcular_fipe_ajustada(veh.get("fipe_valor"), modificacoes)
            cursor.execute(
                "UPDATE veiculos SET modificacoes = %s, fipe_ajustada = %s WHERE id = %s AND user_id = %s",
                (json.dumps(modificacoes, ensure_ascii=False), valor_ajustado, v_id, user_id),
            )
            _salvar_mod_passport_version(cursor, v_id, user_id, modificacoes, veh.get("fipe_valor"), valor_ajustado)
            _invalidate_dashboard_cache_for_user(user_id)
            return jsonify(
                success=True,
                fipe_base=float(veh.get("fipe_valor")) if isinstance(veh.get("fipe_valor"), Decimal) else veh.get("fipe_valor"),
                fipe_ajustada=valor_ajustado,
                pct_ajuste=pct,
                valor_extra=extra,
                aviso=FIPE_AJUSTADA_DISCLAIMER,
            ), 200
    except Exception as e:
        logger.error("Erro ao salvar modificacoes: %s", e, exc_info=True)
        return jsonify(error="Erro interno."), 500


@pages_bp.route("/api/veiculos/<int:v_id>/modificacoes/history", methods=["GET"])
@jwt_required()
def mod_passport_history(v_id):
    """Historico versionado do Mod Passport (evolutivo = lock-in de dados)."""
    user_id = get_jwt_identity()
    try:
        with get_db() as (cursor, conn):
            ok, err = _require_mod_passport(cursor, user_id)
            if not ok:
                return err
            cursor.execute("SELECT id FROM veiculos WHERE id = %s AND user_id = %s", (v_id, user_id))
            if not cursor.fetchone():
                return jsonify(error="Veiculo nao encontrado"), 404
            cursor.execute(
                "SELECT id, created_at, fipe_valor, fipe_ajustada, valor_estimado, snapshot "
                "FROM mod_passport_versions WHERE veiculo_id = %s AND user_id = %s "
                "ORDER BY created_at DESC LIMIT 50",
                (v_id, user_id),
            )
            rows = cursor.fetchall()
        out = []
        for r in rows:
            snap = r.get("snapshot")
            if isinstance(snap, str):
                try:
                    snap = json.loads(snap)
                except (ValueError, TypeError):
                    snap = []
            out.append({
                "id": r["id"],
                "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
                "fipe_valor": r.get("fipe_valor"),
                "fipe_ajustada": r.get("fipe_ajustada"),
                "valor_estimado": r.get("valor_estimado"),
                "qtd_modificacoes": len(snap) if isinstance(snap, list) else 0,
            })
        return jsonify(history=out), 200
    except Exception as e:
        logger.error("Erro historico mod passport: %s", e, exc_info=True)
        return jsonify(error="Erro interno."), 500


@pages_bp.route("/api/veiculos/<int:v_id>/mod-passport/share", methods=["POST"])
@jwt_required()
def share_mod_passport(v_id):
    """Gera um link publico (token) do Mod Passport para compartilhar/exportar."""
    user_id = get_jwt_identity()
    try:
        with get_db() as (cursor, conn):
            ok, err = _require_mod_passport(cursor, user_id)
            if not ok:
                return err
            cursor.execute(
                "SELECT id, marca, modelo, ano_fabricacao, fipe_valor, fipe_ajustada, modificacoes "
                "FROM veiculos WHERE id = %s AND user_id = %s",
                (v_id, user_id),
            )
            veh = cursor.fetchone()
            if not veh:
                return jsonify(error="Veiculo nao encontrado"), 404
            mods = veh.get("modificacoes")
            if isinstance(mods, str):
                try:
                    mods = json.loads(mods)
                except (ValueError, TypeError):
                    mods = []
            token = uuid.uuid4().hex
            cursor.execute(
                """INSERT INTO mod_passport_versions
                   (veiculo_id, user_id, snapshot, fipe_valor, fipe_ajustada, valor_estimado, share_token, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())""",
                (v_id, user_id, json.dumps(mods or [], ensure_ascii=False), veh.get("fipe_valor"),
                 veh.get("fipe_ajustada"), veh.get("fipe_ajustada"), token),
            )
            try:
                conn.commit()
            except Exception:
                pass
            _invalidate_dashboard_cache_for_user(user_id)
        base = request.host_url.rstrip("/")
        url = "{}/mod-passport.html?token={}".format(base, token)
        return jsonify(success=True, share_token=token, share_url=url), 200
    except Exception as e:
        logger.error("Erro compartilhar mod passport: %s", e, exc_info=True)
        return jsonify(error="Erro interno."), 500


@pages_bp.route("/api/public/mod-passport/<token>", methods=["GET"])
def public_mod_passport(token):
    """Acesso publico, somente leitura, do Mod Passport compartilhado."""
    try:
        with get_db() as (cursor, conn):
            cursor.execute(
                """SELECT v.marca, v.modelo, v.ano_fabricacao, v.foto_base64,
                          m.snapshot, m.fipe_valor, m.fipe_ajustada, m.valor_estimado, m.created_at
                   FROM mod_passport_versions m
                   JOIN veiculos v ON v.id = m.veiculo_id
                   WHERE m.share_token = %s LIMIT 1""",
                (token,),
            )
            row = cursor.fetchone()
        if not row:
            return jsonify(error="Mod Passport nao encontrado ou expirou."), 404
        snap = row.get("snapshot")
        if isinstance(snap, str):
            try:
                snap = json.loads(snap)
            except (ValueError, TypeError):
                snap = []
        return jsonify({
            "veiculo": {
                "marca": row.get("marca"),
                "modelo": row.get("modelo"),
                "ano_fabricacao": row.get("ano_fabricacao"),
                "foto_base64": row.get("foto_base64"),
            },
            "fipe_valor": row.get("fipe_valor"),
            "valor_estimado": row.get("valor_estimado") or row.get("fipe_ajustada"),
            "modificacoes": snap or [],
            "criado_em": row["created_at"].isoformat() if row.get("created_at") else None,
            "aviso": "Estimativa gerada por IA. Nao substitui vistoria.",
        }), 200
    except Exception as e:
        logger.error("Erro public mod passport: %s", e, exc_info=True)
        return jsonify(error="Erro interno."), 500


@pages_bp.route("/api/public/mod-passport/<token>/pdf", methods=["GET"])
def public_mod_passport_pdf(token):
    """Exporta o Mod Passport compartilhado em PDF."""
    try:
        with get_db() as (cursor, conn):
            cursor.execute(
                """SELECT v.marca, v.modelo, v.ano_fabricacao, v.fipe_valor,
                          m.snapshot, m.fipe_ajustada, m.valor_estimado
                   FROM mod_passport_versions m
                   JOIN veiculos v ON v.id = m.veiculo_id
                   WHERE m.share_token = %s LIMIT 1""",
                (token,),
            )
            row = cursor.fetchone()
        if not row:
            return jsonify(error="Mod Passport nao encontrado ou expirou."), 404
        snap = row.get("snapshot")
        if isinstance(snap, str):
            try:
                snap = json.loads(snap)
            except (ValueError, TypeError):
                snap = []
        veiculo = {
            "marca": row.get("marca"),
            "modelo": row.get("modelo"),
            "ano_fabricacao": row.get("ano_fabricacao"),
            "fipe_valor": row.get("fipe_valor"),
        }
        pdf_bytes = _build_modpassport_pdf(veiculo, snap, row.get("valor_estimado") or row.get("fipe_ajustada"))
        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=True,
            download_name="mod_passport.pdf",
        )
    except Exception as e:
        logger.error("Erro pdf mod passport: %s", e, exc_info=True)
        return jsonify(error="Erro interno."), 500

