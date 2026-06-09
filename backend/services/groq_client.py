import logging
import os
import time
import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_PRIMARY_MODEL = "groq/compound-mini"
DEFAULT_UTILITY_MODEL = "llama-3.1-8b-instant"
DEFAULT_VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
DEFAULT_FALLBACK_MODELS = ("groq/compound",)
DEFAULT_VISION_FALLBACK_MODELS = ()
TEXT_ONLY_MODELS = {"groq/compound", "groq/compound-mini"}
RETRYABLE_STATUS_CODES = {408, 409, 429, 500, 502, 503, 504}
_warned_text_only_vision_models = set()


class GroqAPIError(RuntimeError):
    pass


class GroqConfigurationError(GroqAPIError):
    pass


class GroqHTTPError(GroqAPIError):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


def _read_int_env(name, default, minimum=0):
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def _read_float_env(name, default):
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _parse_model_list(raw_value, default_models):
    source = raw_value if raw_value is not None else ",".join(default_models)
    models = []
    seen = set()

    for item in str(source).split(","):
        model = item.strip()
        if model and model not in seen:
            seen.add(model)
            models.append(model)

    return tuple(models)


def _settings():
    api_key = (os.getenv("API_GROQ") or os.getenv("GROQ_API_KEY") or "").strip()
    if not api_key:
        raise GroqConfigurationError("API_GROQ ou GROQ_API_KEY nao configurada.")

    return {
        "api_key": api_key,
        "base_url": (os.getenv("GROQ_BASE_URL") or DEFAULT_BASE_URL).rstrip("/"),
        "primary_model": (os.getenv("GROQ_PRIMARY_MODEL") or DEFAULT_PRIMARY_MODEL).strip(),
        "utility_model": (os.getenv("GROQ_UTILITY_MODEL") or DEFAULT_UTILITY_MODEL).strip(),
        "vision_model": (os.getenv("GROQ_VISION_MODEL") or DEFAULT_VISION_MODEL).strip(),
        "vision_fallback_models": _parse_model_list(
            os.getenv("GROQ_VISION_FALLBACK_MODELS"),
            DEFAULT_VISION_FALLBACK_MODELS,
        ),
        "fallback_models": _parse_model_list(
            os.getenv("GROQ_FALLBACK_MODELS"),
            DEFAULT_FALLBACK_MODELS,
        ),
        "timeout": _read_int_env("GROQ_TIMEOUT_SECONDS", 60, minimum=5),
        "max_retries": _read_int_env("GROQ_MAX_RETRIES", 3, minimum=1),
        "temperature": _read_float_env("GROQ_TEMPERATURE", 0.7),
    }


def _normalize_vision_model(model_name):
    normalized_model = str(model_name or "").strip()
    if normalized_model in TEXT_ONLY_MODELS:
        if normalized_model not in _warned_text_only_vision_models:
            logger.warning(
                "GROQ_VISION_MODEL=%s nao aceita imagens; usando %s.",
                normalized_model,
                DEFAULT_VISION_MODEL,
            )
            _warned_text_only_vision_models.add(normalized_model)
        return DEFAULT_VISION_MODEL
    return normalized_model


def model_chain(primary_model=None, fallback_models=None):
    settings = _settings()
    seen = set()
    fallback_chain = settings["fallback_models"] if fallback_models is None else tuple(fallback_models)

    for model in (primary_model or settings["primary_model"], *fallback_chain):
        model_name = str(model or "").strip()
        if model_name and model_name not in seen:
            seen.add(model_name)
            yield model_name


def vision_model():
    return _normalize_vision_model(_settings()["vision_model"])


def utility_model():
    return _settings()["utility_model"]


def vision_fallback_models():
    return _settings()["vision_fallback_models"]


def build_chat_messages(system_instruction, prompt, history=None):
    messages = []
    if system_instruction:
        messages.append({"role": "system", "content": str(system_instruction)})

    for item in history or []:
        role = "assistant" if item.get("role") in ("assistant", "model") else "user"
        content = str(item.get("content") or "").strip()
        if content:
            messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": str(prompt or "")})
    return messages


def chat_completion(
    messages,
    *,
    primary_model=None,
    fallback_models=None,
    response_format=None,
    temperature=None,
    log_context="Groq",
):
    settings = _settings()
    last_error = None
    models = tuple(model_chain(primary_model, fallback_models=fallback_models))

    for model_index, model_name in enumerate(models):
        for attempt in range(settings["max_retries"]):
            try:
                return _request_chat_completion(
                    settings,
                    model_name,
                    messages,
                    response_format=response_format,
                    temperature=temperature,
                )
            except GroqHTTPError as error:
                last_error = error
                if not _should_retry_http_error(error):
                    break
                if attempt + 1 >= settings["max_retries"]:
                    break
                _wait_before_retry(attempt, log_context, model_name, error)
            except requests.RequestException as error:
                last_error = error
                if attempt + 1 >= settings["max_retries"]:
                    break
                _wait_before_retry(attempt, log_context, model_name, error)

        if model_index + 1 < len(models):
            logger.warning("%s falhou com modelo %s. Tentando fallback.", log_context, model_name)
        else:
            logger.warning("%s falhou com modelo %s.", log_context, model_name)

    raise last_error or GroqAPIError(f"{log_context} falhou sem modelos configurados.")


def _request_chat_completion(settings, model_name, messages, *, response_format=None, temperature=None):
    payload = {
        "model": model_name,
        "messages": messages,
        "temperature": settings["temperature"] if temperature is None else temperature,
    }
    if response_format:
        payload["response_format"] = response_format

    response = requests.post(
        f"{settings['base_url']}/chat/completions",
        headers={
            "Authorization": f"Bearer {settings['api_key']}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=settings["timeout"],
    )

    if response.status_code >= 400:
        raise GroqHTTPError(response.status_code, _response_error_message(response))

    data = response.json()
    choices = data.get("choices") or []
    if not choices:
        raise GroqAPIError("Resposta Groq sem choices.")

    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, list):
        return "\n".join(
            str(part.get("text") or "") for part in content if isinstance(part, dict)
        ).strip()
    return str(content or "").strip()


def _response_error_message(response):
    try:
        payload = response.json()
    except ValueError:
        return response.text[:500]

    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or error)[:500]
    return str(payload)[:500]


def _should_retry_http_error(error):
    if error.status_code in (400, 401, 403, 404, 429):
        return False
    return error.status_code in RETRYABLE_STATUS_CODES


def _wait_before_retry(attempt, log_context, model_name, error):
    delay = min(2 ** attempt, 8)
    logger.warning(
        "%s falhou com %s na tentativa %s: %s. Nova tentativa em %ss.",
        log_context,
        model_name,
        attempt + 1,
        error,
        delay,
    )
    time.sleep(delay)
