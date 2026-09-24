"""Split de routes/pages.py — módulo pages_misc (P1).

Carregado via exec() em routes/pages.py compartilhando os mesmos globals
(imports, pages_bp, constantes, logger). Não importar diretamente.
"""

@pages_bp.route("/api/onboarding/revisao", methods=["POST"])
@jwt_required(optional=True)
def onboarding_sugestao_revisao():
    data = request.get_json(silent=True) or {}
    marca = (data.get("marca") or "").strip()
    modelo = (data.get("modelo") or "").strip()
    ano = data.get("ano_fabricacao")
    km = data.get("quilometragem")
    if not marca or not modelo:
        return jsonify(error="Informe marca e modelo."), 400
    try:
        sugestao = _sugerir_revisao(marca, modelo, ano, km)
        return jsonify(sugestao=sugestao), 200
    except Exception as e:
        logger.error("Erro na sugestao de revisao: %s", e, exc_info=True)
        return jsonify(sugestao=""), 200


def _sanitizar_sugestao(texto):
    """Aplica guardrails ao texto gerado pela IA (seguranca e escopo)."""
    if not texto:
        return _SUGESTAO_PADRAO
    t = re.sub(r"\s+", " ", texto).strip()
    for pat in _FORBIDDEN_PATTERNS:
        t = t.replace(pat, "")
    # remove citacoes de precos (R$ 1.234,56)
    t = re.sub(r"R\$\s?[\d\.,]+", "", t)
    t = t.strip(" \"'")
    t = t[:600]
    if len(t) < 10 or any(p in t.lower() for p in _REFUSAL_PATTERNS):
        return _SUGESTAO_PADRAO
    return t


def _sugerir_revisao(marca, modelo, ano, km):
    """Gera (via modelo utilitario, com cache) um plano de revisao preventiva."""
    from services.nogai import _generate_content_with_fallback
    from services.groq_client import utility_model, utility_fallback_models
    from utils.cache import make_cache_key, cache_get_json, cache_set_json
    prompt = (
        "Voce e o NOG, consultor de manutencao automotiva da AutoAssist. "
        "REGRA: sugira APENAS itens de revisao preventiva comuns e seguros "
        "(ex.: troca de oleo, filtros, freios, pneus, fluidos, bateria). "
        "NAO faca diagnostico de avarias, NAO recomende procedimentos perigosos, "
        "NAO cite precos nem orcamentos, NAO inclua links, NAO aborde temas fora "
        "de automoveis. Responda somente em portugues, com 3 a 5 bullet points "
        "curtos e linguagem simples. Se faltarem dados, baseie-se no padrao geral."
        + chr(10) + chr(10) +
        "Veiculo: " + marca + " " + modelo + " " + str(ano or "") + " - " + str(km or "km nao informado") + " km"
    )
    cache_key = make_cache_key("onboarding:revisao", marca, modelo, str(ano), str(km))
    cached = cache_get_json(cache_key)
    if cached is not None:
        return cached
    obj = _generate_content_with_fallback(
        contents=prompt,
        primary_model=utility_model(),
        fallback_models=utility_fallback_models(),
        temperature=0.3,
        log_context="Onboarding revisao",
    )
    texto = _sanitizar_sugestao(obj.text or "")
    cache_set_json(cache_key, texto, ttl=86400)
    return texto


@pages_bp.route("/api/admin/analytics/burn", methods=["GET"])
@jwt_required()
def admin_burn_analytics():
    """§5: burn de IA por usuário no mês corrente (via tabela chats). Apenas admin."""
    admin_id = get_jwt_identity()
    with get_db() as (cursor, conn):
        cursor.execute("SELECT is_admin FROM users WHERE id = %s", (admin_id,))
        row = cursor.fetchone()
        if not row or not row.get("is_admin"):
            return jsonify(error="Acesso restrito."), 403
        cursor.execute(
            """
            SELECT u.id, u.nome, u.email, u.is_premium,
                   COUNT(c.id) AS msgs_mes,
                   MAX(c.created_at) AS ultima_interacao
            FROM users u
            LEFT JOIN chats c ON c.user_id = u.id AND c.created_at >= DATE_FORMAT(NOW(), '%Y-%m-01')
            GROUP BY u.id
            ORDER BY msgs_mes DESC
            LIMIT 100
            """
        )
        rows = cursor.fetchall()
    return jsonify(users=rows, mes=datetime.now().strftime("%Y-%m")), 200


@pages_bp.route("/api/report", methods=["POST"])
@jwt_required()
def generate_report():
    user_id = get_jwt_identity()
    data = request.get_json()
    text = data.get("text")

    if not text:
        return jsonify(error="Texto da análise é obrigatório"), 400

    try:
        with get_db() as (cursor, conn):
            user = get_user_by_id(cursor, user_id)
            if not user:
                return invalid_session_response()

            # Criar diretório seguro se não existir
            secure_reports_dir = os.path.join(current_app.root_path, "secure_reports")
            if not os.path.exists(secure_reports_dir):
                os.makedirs(secure_reports_dir)

            # Nome de arquivo único e imprevisível
            filename = f"report_{user_id}_{uuid.uuid4().hex}.pdf"
            filepath = os.path.join(secure_reports_dir, filename)

            # Gerar o PDF
            from services.report_generator import criar_relatorio_pdf
            success = criar_relatorio_pdf(user, text, filepath)

            if success:
                # Retornar URL da rota que serve o arquivo (com auth)
                return jsonify(url=f"/api/report/{filename}"), 200
            else:
                return jsonify(error="Erro ao gerar relatório"), 500
    except Exception as e:
        logger.error(f"Erro ao gerar relatório: {e}")
        return jsonify(error="Erro interno ao gerar relatório"), 500


@pages_bp.route("/api/report/<filename>", methods=["GET"])
@jwt_required()
def serve_report(filename):
    user_id = str(get_jwt_identity())

    # Segurança básica contra Path Traversal
    if ".." in filename or "/" in filename or "\\" in filename:
        return jsonify(error="Nome de arquivo inválido"), 400

    # Verificar se o arquivo pertence ao usuário (prefixo report_USERID_)
    if not filename.startswith(f"report_{user_id}_"):
        logger.warning(f"Tentativa de IDOR: Usuário {user_id} tentou acessar {filename}")
        return jsonify(error="Acesso negado"), 403

    secure_reports_dir = os.path.join(current_app.root_path, "secure_reports")
    return send_from_directory(secure_reports_dir, filename)

