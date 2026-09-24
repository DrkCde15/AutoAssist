"""Split de routes/pages.py — módulo pages_static (P1).

Carregado via exec() em routes/pages.py compartilhando os mesmos globals
(imports, pages_bp, constantes, logger). Não importar diretamente.
"""

@limiter.exempt
@pages_bp.route("/")
def index():
    return current_app.send_static_file("index.html")


@limiter.exempt
@pages_bp.route("/<path:path>")
def serve_html(path):
    if path.startswith("api/"):
        return jsonify(error="Recurso nao encontrado."), 404
    if path in ("robots.txt", "llms.txt", "sitemap.xml"):
        return jsonify(error="Recurso nao encontrado."), 404
    if not path.endswith(".html") and "." not in path:
        path += ".html"
    return current_app.send_static_file(path)

