import functools
import hmac
import os

from flask import jsonify, request


def require_cron_secret(header_name: str = "X-Cron-Secret"):
    """Decorador que exige o segredo de cron (MAINTENANCE_EMAIL_CRON_SECRET) no header.

    Use em rotas agendadas expostas via HTTP para que só quem possui o segredo
    (ex.: o job de cron externo) consiga acioná-las. Sem o segredo configurado
    no ambiente, a rota recusa com 500 para evitar acesso acidental.
    """

    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            expected = (os.getenv("MAINTENANCE_EMAIL_CRON_SECRET") or "").strip()
            if not expected:
                return jsonify(error="Cron auth nao configurado"), 500
            provided = request.headers.get(header_name) or ""
            if not provided or not hmac.compare_digest(provided, expected):
                return jsonify(error="Acesso negado"), 403
            return view(*args, **kwargs)

        return wrapper

    return decorator
