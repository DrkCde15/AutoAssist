import base64
import logging

import pytest
from unittest import mock

import services.nogai as nogai
import services.vision_ai as vision
import services.attachment_ai as attachment_ai
from utils.cache import _local_json_cache, get_redis_client

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

FAKE_JSON = '{"intervalo_dias": 90, "intervalo_km": 5000, "justificativa": "teste"}'
FAKE_DICT = {"intervalo_dias": 90, "intervalo_km": 5000, "justificativa": "teste"}


@pytest.fixture(autouse=True)
def _reset_cache_state():
    import utils.cache as cache_mod

    cache_mod._REDIS_CLIENT = None
    cache_mod._REDIS_UNAVAILABLE = False
    _local_json_cache.clear()
    client = get_redis_client()
    if client is not None:
        try:
            for key in client.scan_iter("groq:*"):
                client.delete(key)
        except Exception:
            pass
    yield


def test_ai_cache_miss_then_hit():
    calls = {"n": 0}

    def fake_chat(*_args, **_kwargs):
        calls["n"] += 1
        return FAKE_JSON

    with mock.patch.object(nogai, "chat_completion", fake_chat), \
         mock.patch.object(vision, "chat_completion", fake_chat):
        r1 = nogai.prever_intervalo_manutencao("troca de oleo do motor", "carro 1.0")
        r2 = nogai.prever_intervalo_manutencao("troca de oleo do motor", "carro 1.0")
        assert r1 == r2 == FAKE_DICT

        v1 = vision.analisar_imagem("AAAA", "tem defeito?")
        v2 = vision.analisar_imagem("AAAA", "tem defeito?")
        assert v1 == v2 == FAKE_JSON

    # 1 chamada Groq real por prompt unico (previsao + visao)
    assert calls["n"] == 2


def test_file_analysis_cache_miss_then_hit():
    calls = {"n": 0}

    def fake_chat(*_args, **_kwargs):
        calls["n"] += 1
        return FAKE_JSON

        with mock.patch.object(attachment_ai, "chat_completion", fake_chat), \
         mock.patch.object(vision, "chat_completion", fake_chat), \
         mock.patch.object(attachment_ai, "extract_pdf_text", return_value="texto extraido do pdf"):
            # Imagem via analisar_arquivo
            img_bytes = b"fake-image-bytes"
            a1 = attachment_ai.analisar_arquivo(img_bytes, "image/png", "foto.png", "defeito?")
            a2 = attachment_ai.analisar_arquivo(img_bytes, "image/png", "foto.png", "defeito?")
            assert a1 == a2 == FAKE_JSON

            # PDF via analisar_arquivo
            pdf_bytes = b"fake-pdf-bytes"
            p1 = attachment_ai.analisar_arquivo(pdf_bytes, "application/pdf", "doc.pdf", "revisar?")
            p2 = attachment_ai.analisar_arquivo(pdf_bytes, "application/pdf", "doc.pdf", "revisar?")
            assert p1 == p2 == FAKE_JSON

        # 1 chamada Groq real por arquivo unico (imagem + pdf)
        assert calls["n"] == 2
