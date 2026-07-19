"""Testes de seguranca do backend: cron auth e webhook Cakto.

Estes testes validam:
1. require_cron_secret bloqueia requisicoes sem o segredo e aceita com o header.
2. CaktoService nao aceita mais o secret via query string por padrao.
"""
import importlib.util
import os
import sys
from pathlib import Path
from unittest import mock

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))


def _load(module_name, path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


import flask


def _app_context():
    app = flask.Flask(__name__)
    return app.app_context()


def test_require_cron_secret_rejects_without_header():
    cron_auth = _load("utils.cron_auth", BACKEND / "utils" / "cron_auth.py")
    with mock.patch.dict(os.environ, {"MAINTENANCE_EMAIL_CRON_SECRET": "supersecret"}, clear=True):
        calls = {}

        def view():
            calls["hit"] = True
            return "ok"

        # Substitui o proxy `request` do flask por um Mock isolado.
        fake_request = mock.MagicMock()
        cron_auth.request = fake_request
        wrapped = cron_auth.require_cron_secret()(view)
        # Sem header -> 403
        fake_request.headers.get.return_value = ""
        with _app_context():
            resp = wrapped()
        assert resp[1] == 403, resp
        assert "hit" not in calls


def test_require_cron_secret_accepts_with_header():
    cron_auth = _load("utils.cron_auth", BACKEND / "utils" / "cron_auth.py")
    with mock.patch.dict(os.environ, {"MAINTENANCE_EMAIL_CRON_SECRET": "supersecret"}, clear=True):
        calls = {}

        def view():
            calls["hit"] = True
            return "ok"

        fake_request = mock.MagicMock()
        cron_auth.request = fake_request
        wrapped = cron_auth.require_cron_secret()(view)
        fake_request.headers.get.return_value = "supersecret"
        with _app_context():
            resp = wrapped()
        assert calls.get("hit") is True
        assert resp == "ok"


def test_require_cron_secret_missing_env_returns_500():
    cron_auth = _load("utils.cron_auth", BACKEND / "utils" / "cron_auth.py")
    with mock.patch.dict(os.environ, {}, clear=True):
        fake_request = mock.MagicMock()
        cron_auth.request = fake_request
        fake_request.headers.get.return_value = "x"
        with _app_context():
            resp = cron_auth.require_cron_secret()(lambda: "ok")()
        assert resp[1] == 500


def test_cakto_query_secret_disabled_by_default():
    cakto = _load("services.cakto", BACKEND / "services" / "cakto.py")
    with mock.patch.dict(os.environ, {"CAKTO_WEBHOOK_SECRET": "wsecret"}, clear=True):
        svc = cakto.CaktoService()
        # Por padrao (sem CAKTO_ACCEPT_QUERY_SECRET) query secret deve ser ignorado.
        assert svc.accept_query_secret is False

        ok, _ = svc.validate_secret(payload={}, headers={}, query_secret="wsecret")
        assert ok is False, "secret via query string nao deve ser aceito por padrao"

        ok_hdr, _ = svc.validate_secret(
            payload={}, headers={"X-Cakto-Secret": "wsecret"}, query_secret=None
        )
        assert ok_hdr is True, "secret via header deve continuar valido"
