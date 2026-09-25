"""Split de routes/pages.py — módulo pages_static (P1).

Carregado via exec() em routes/pages.py compartilhando os mesmos globals
(imports, pages_bp, constantes, logger). Não importar diretamente.
"""

from typing import TYPE_CHECKING
if TYPE_CHECKING:  # noqa: F401 — nomes providos em runtime pelos globals de routes/pages.py (exec)
    from flask import current_app
    from flask import jsonify
    from extensions import limiter
    from ..pages import pages_bp

@limiter.exempt
@pages_bp.route("/")
def index():
    return current_app.send_static_file("index.html")


@limiter.exempt
@pages_bp.route("/<path:path>")
def serve_html(path):
    # Defesa: base64 colado na URL (ex.: <img src> com foto crua) — rejeita
    # cedo sem tentar resolver arquivo nem poluir log com a URI gigante.
    if len(path) > 2000:
        return jsonify(error="URI muito longa."), 414
    if path.startswith("api/"):
        return jsonify(error="Recurso nao encontrado."), 404
    if path in ("robots.txt", "llms.txt", "sitemap.xml"):
        return jsonify(error="Recurso nao encontrado."), 404
    if not path.endswith(".html") and "." not in path:
        path += ".html"
    return current_app.send_static_file(path)

