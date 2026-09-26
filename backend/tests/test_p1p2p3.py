"""P1/P2/P3 — validação das entregas (schemas, storage, métricas, rate-limit, OpenAPI, split, CSP)."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from schemas.chat import ChatInput
from schemas.b2b import B2BDiagnosisInput, B2BCreateKeyInput


class SchemasTest(unittest.TestCase):
    def test_chat_valid(self):
        p = ChatInput.model_validate({"message": "  oi  ", "lat": -23.5, "lng": -46.6})
        self.assertEqual(p.message, "oi")
        self.assertTrue(p.has_content())

    def test_chat_rejects_oversize(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            ChatInput.model_validate({"message": "x" * 5000})

    def test_chat_extra_ignored(self):
        p = ChatInput.model_validate({"message": "a", "campo_legado": 1})
        self.assertEqual(p.message, "a")

    def test_b2b_resolves_image_alias(self):
        p = B2BDiagnosisInput.model_validate({"image_b64": "abc", "formato": "PDF"})
        self.assertEqual(p.resolved_image(), "abc")
        self.assertEqual(p.formato, "pdf")

    def test_b2b_key_limits(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            B2BCreateKeyInput.model_validate({"nome": "x", "rate_limit_per_min": 9999})


class PhotoStorageTest(unittest.TestCase):
    # Isola do .env real (pode apontar p/ S3/MinIO sem servidor no ar)
    @patch.dict("os.environ", {"VEHICLE_PHOTO_BACKEND": "local"})
    def test_parse_and_local_roundtrip(self):
        import base64
        from services.vehicle_photo_storage import parse_data_url, get_storage
        # PNG 1x1
        tiny_png_b64 = (
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
        )
        data, mime = parse_data_url(tiny_png_b64)
        self.assertEqual(mime, "image/png")
        store = get_storage()
        key = store.save(999, 888, data, mime)
        try:
            found = store.get(key)
            self.assertIsNotNone(found)
            self.assertEqual(found[1], "image/png")
        finally:
            store.delete(key)
            self.assertIsNone(store.get(key))

    def test_rejects_non_image(self):
        import base64
        from services.vehicle_photo_storage import parse_data_url
        with self.assertRaises(ValueError):
            parse_data_url(base64.b64encode(b"not-an-image-at-all-xyz").decode())


class GroqMetricsTest(unittest.TestCase):
    def test_record_and_snapshot(self):
        from unittest.mock import patch
        from services import groq_metrics
        with patch("utils.cache.get_redis_client", return_value=None):
            groq_metrics.reset()
            groq_metrics.record("chat", "model-t", {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15})
            snap = groq_metrics.snapshot()
            self.assertEqual(snap["total_tokens"], 15)
            self.assertEqual(snap["metrics"][0]["endpoint"], "chat")
            groq_metrics.reset()


class RateLimitTest(unittest.TestCase):
    def test_ws_allows_then_blocks(self):
        from utils import rate_limit
        key = "rate-limit-test-guest-xyz"
        # esgota a janela
        for _ in range(rate_limit.CHAT_WS_MAX_PER_MIN):
            self.assertTrue(rate_limit.ws_chat_allowed(None, key))
        self.assertFalse(rate_limit.ws_chat_allowed(None, key))


class OpenApiSplitCspTest(unittest.TestCase):
    def test_openapi_yaml_loads(self):
        from openapi_loader import load_spec
        spec = load_spec("http://localhost:5001")
        self.assertIn("/api/chat", spec.get("paths", {}))
        self.assertIn("/api/admin/groq-metrics", spec.get("paths", {}))
        self.assertIn("/api/b2b/diagnosis", spec.get("paths", {}))

    def test_pages_split_imports(self):
        import routes.pages as p
        for name in ["chat", "upload_veiculo_foto", "serve_veiculo_foto",
                     "register_maintenance_history", "parse_chat_attachment",
                     "generate_assistant_payload", "pages_bp"]:
            self.assertTrue(hasattr(p, name), name)

    def test_csp_no_unsafe_eval_by_default(self):
        src = (BACKEND_DIR / "app.py").read_text()
        # default deve ser sem unsafe-eval hardcoded; gate via env
        self.assertIn("CSP_ALLOW_UNSAFE_EVAL", src)
        self.assertIn("object-src", src)
        self.assertIn("base-uri", src)


if __name__ == "__main__":
    unittest.main()
