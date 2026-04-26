import calendar
import json
import re
import unicodedata
from datetime import date, datetime, timedelta
from decimal import Decimal


MAINTENANCE_RULES = {
    "troca_oleo": {
        "label": "Troca de oleo",
        "keywords": ["oleo", "filtro de oleo", "lubrificante"],
        "default_interval_days": 180,
        "default_interval_km": 10000,
    },
    "pneus": {
        "label": "Pneus",
        "keywords": ["pneu", "pneus", "rodizio", "rodizio de pneus", "alinhamento", "balanceamento"],
        "default_interval_days": 180,
        "default_interval_km": 10000,
    },
    "freios": {
        "label": "Freios",
        "keywords": ["freio", "pastilha", "disco", "fluido de freio"],
        "default_interval_days": 365,
        "default_interval_km": 20000,
    },
    "bateria": {
        "label": "Bateria",
        "keywords": ["bateria"],
        "default_interval_days": 730,
        "default_interval_km": None,
    },
    "correia_dentada": {
        "label": "Correia dentada",
        "keywords": ["correia dentada", "correia", "tensor"],
        "default_interval_days": 1460,
        "default_interval_km": 60000,
    },
    "filtro_ar": {
        "label": "Filtro de ar",
        "keywords": ["filtro de ar", "filtro"],
        "default_interval_days": 365,
        "default_interval_km": 15000,
    },
    "arrefecimento": {
        "label": "Liquido de arrefecimento",
        "keywords": ["arrefecimento", "radiador", "aditivo", "liquido de arrefecimento"],
        "default_interval_days": 730,
        "default_interval_km": 40000,
    },
    "suspensao": {
        "label": "Suspensao",
        "keywords": ["suspensao", "amortecedor", "bucha", "coxim"],
        "default_interval_days": 730,
        "default_interval_km": 40000,
    },
    "revisao_geral": {
        "label": "Revisao geral",
        "keywords": ["revisao", "checkup", "inspecao", "inspecao geral"],
        "default_interval_days": 365,
        "default_interval_km": 10000,
    },
    "manutencao_geral": {
        "label": "Manutencao geral",
        "keywords": [],
        "default_interval_days": None,
        "default_interval_km": None,
    },
}


PT_MONTHS = {
    "janeiro": 1,
    "fevereiro": 2,
    "marco": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}


def normalize_text(text):
    raw = text or ""
    normalized = unicodedata.normalize("NFKD", raw)
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return normalized.lower()


def to_float(value):
    if value is None:
        return None
    if isinstance(value, float):
        return value
    if isinstance(value, int):
        return float(value)
    if isinstance(value, Decimal):
        return float(value)

    text = str(value).strip().lower()
    if not text:
        return None
    text = text.replace("r$", "").replace("rs", "").replace(" ", "")
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    elif "." in text:
        fraction = text.split(".")[-1]
        if len(fraction) == 3:
            text = text.replace(".", "")
    try:
        return float(text)
    except ValueError:
        return None


def to_int(value):
    parsed = to_float(value)
    if parsed is None:
        return None
    return int(round(parsed))


def _safe_date(year, month, day):
    try:
        return date(year, month, day)
    except ValueError:
        return None


def add_months(base_date, months):
    month_index = base_date.month - 1 + months
    year = base_date.year + (month_index // 12)
    month = (month_index % 12) + 1
    day = min(base_date.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def add_years(base_date, years):
    try:
        return base_date.replace(year=base_date.year + years)
    except ValueError:
        return base_date.replace(month=2, day=28, year=base_date.year + years)


def _apply_interval(base_date, value, unit):
    unit = unit.lower()
    if unit.startswith("dia"):
        return base_date + timedelta(days=value)
    if unit.startswith("mes"):
        return add_months(base_date, value)
    if unit.startswith("ano"):
        return add_years(base_date, value)
    return None


def parse_date_input(raw_value, fallback_date=None):
    if isinstance(raw_value, datetime):
        return raw_value.date()
    if isinstance(raw_value, date):
        return raw_value
    if raw_value is None:
        return fallback_date

    text = normalize_text(str(raw_value).strip())
    today = fallback_date or date.today()
    if not text:
        return fallback_date

    if "anteontem" in text:
        return today - timedelta(days=2)
    if "ontem" in text:
        return today - timedelta(days=1)
    if "hoje" in text:
        return today

    iso_match = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", text)
    if iso_match:
        parsed = _safe_date(int(iso_match.group(1)), int(iso_match.group(2)), int(iso_match.group(3)))
        if parsed:
            return parsed

    br_match = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b", text)
    if br_match:
        day = int(br_match.group(1))
        month = int(br_match.group(2))
        year = br_match.group(3)
        if year:
            year = int(year)
            if year < 100:
                year += 2000
        else:
            year = today.year
        parsed = _safe_date(year, month, day)
        if parsed and not br_match.group(3):
            # Historial usually refers to past events. If future date without year,
            # assume it belongs to previous year.
            if parsed > today + timedelta(days=7):
                parsed = _safe_date(year - 1, month, day) or parsed
        if parsed:
            return parsed

    named_month_match = re.search(
        r"\b(\d{1,2})\s+de\s+(janeiro|fevereiro|marco|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)(?:\s+de\s+(\d{4}))?\b",
        text,
    )
    if named_month_match:
        day = int(named_month_match.group(1))
        month = PT_MONTHS.get(named_month_match.group(2))
        year = int(named_month_match.group(3)) if named_month_match.group(3) else today.year
        parsed = _safe_date(year, month, day)
        if parsed and not named_month_match.group(3) and parsed > today + timedelta(days=7):
            parsed = _safe_date(year - 1, month, day) or parsed
        if parsed:
            return parsed

    return fallback_date


def detect_maintenance_type(text):
    normalized = normalize_text(text)
    best_key = "manutencao_geral"
    best_score = 0

    for key, config in MAINTENANCE_RULES.items():
        if not config["keywords"]:
            continue
        score = 0
        for kw in config["keywords"]:
            if kw in normalized:
                score += 1
        if score > best_score:
            best_score = score
            best_key = key

    rule = MAINTENANCE_RULES[best_key]
    return best_key, rule["label"], rule["default_interval_days"], rule["default_interval_km"], best_score


def extract_cost(text):
    normalized = normalize_text(text)
    number_group = r"(\d{1,3}(?:[.\s]\d{3})*(?:,\d{1,2})?|\d+(?:,\d{1,2})?)"
    patterns = [
        rf"(?:r\$|rs\$?)\s*{number_group}",
        rf"{number_group}\s*(?:reais?|r\$|rs\$?)",
        rf"(?:gastei|paguei|custou|valor(?:\s+total)?(?:\s+foi)?)\s*(?:de\s*)?(?:r\$\s*)?{number_group}",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if match:
            return to_float(match.group(1))
    return None


def extract_intervals(text, service_date):
    normalized = normalize_text(text)

    date_interval = None
    km_interval = None
    next_due_date = None

    date_match = re.search(
        r"(?:a cada|daqui a?|proxima(?:\s+troca)?\s+em|proximo(?:\s+servico)?\s+em|retornar em)\s*(\d{1,3})\s*(dias?|mes(?:es)?|anos?)",
        normalized,
    )
    if date_match:
        value = int(date_match.group(1))
        unit = date_match.group(2)
        computed_due = _apply_interval(service_date, value, unit)
        if computed_due:
            date_interval = (computed_due - service_date).days
            next_due_date = computed_due

    km_match = re.search(
        r"(?:a cada|daqui a?|proxima(?:\s+troca)?\s+em|proximo(?:\s+servico)?\s+com|retornar com)\s*(\d{1,3}(?:[.,]\d{3})*|\d+(?:[.,]\d+)?)\s*(mil|k)?\s*(?:km|quilometros?)",
        normalized,
    )
    if km_match:
        km_value = to_float(km_match.group(1))
        if km_value is not None:
            scale = km_match.group(2)
            if scale in ("mil", "k") and km_value < 1000:
                km_value *= 1000
            km_interval = int(round(km_value))

    return date_interval, km_interval, next_due_date


def extract_service_km(text):
    normalized = normalize_text(text)
    interval_pattern = (
        r"(?:a cada|daqui a?|proxima(?:\s+troca)?\s+em|proximo(?:\s+servico)?\s+com|retornar com)\s*"
        r"(?:\d{1,3}(?:[.,]\d{3})*|\d+(?:[.,]\d+)?)\s*(?:mil|k)?\s*(?:km|quilometros?)"
    )
    normalized = re.sub(interval_pattern, " ", normalized)

    context_match = re.search(
        r"(?:com|aos|estava com|marcando|atual(?:mente)?(?:\s+em)?)\s*(\d{1,3}(?:[.\s]\d{3})+|\d{3,7})\s*(?:km|quilometros?)",
        normalized,
    )
    if context_match:
        return to_int(context_match.group(1))

    generic_match = re.search(r"\b(\d{1,3}(?:[.\s]\d{3})+|\d{4,7})\s*(?:km|quilometros?)\b", normalized)
    if generic_match:
        return to_int(generic_match.group(1))

    return None


def parse_maintenance_entry(description, fallback_date=None):
    service_date = parse_date_input(description, fallback_date=fallback_date or date.today()) or date.today()
    detected_type, label, default_days, default_km, score = detect_maintenance_type(description)
    cost = extract_cost(description)
    explicit_interval_days, explicit_interval_km, explicit_next_due_date = extract_intervals(description, service_date)
    service_km = extract_service_km(description)

    interval_days = explicit_interval_days if explicit_interval_days is not None else default_days
    interval_km = explicit_interval_km if explicit_interval_km is not None else default_km

    next_due_date = explicit_next_due_date
    if next_due_date is None and interval_days:
        next_due_date = service_date + timedelta(days=interval_days)

    next_due_km = None
    if service_km is not None and interval_km:
        next_due_km = service_km + interval_km

    return {
        "description": description,
        "maintenance_type": detected_type,
        "maintenance_label": label,
        "service_date": service_date,
        "service_km": service_km,
        "cost": cost,
        "interval_days": interval_days,
        "interval_km": interval_km,
        "next_due_date": next_due_date,
        "next_due_km": next_due_km,
        "parser_metadata": {
            "confidence_score": score,
            "detected_by_keywords": score > 0,
            "default_interval_applied": (
                (explicit_interval_days is None and default_days is not None)
                or (explicit_interval_km is None and default_km is not None)
            ),
            "explicit_interval_detected": (
                explicit_interval_days is not None or explicit_interval_km is not None
            ),
        },
    }


def apply_manual_overrides(parsed_payload, data, fallback_service_km=None):
    payload = dict(parsed_payload)
    fallback_date = payload.get("service_date") or date.today()

    manual_date = parse_date_input(data.get("data_servico"), fallback_date=fallback_date)
    if manual_date:
        payload["service_date"] = manual_date

    manual_cost = to_float(data.get("custo"))
    if manual_cost is not None:
        payload["cost"] = manual_cost

    manual_km = to_int(data.get("quilometragem_servico"))
    if manual_km is not None:
        payload["service_km"] = manual_km
    elif payload.get("service_km") is None and fallback_service_km is not None:
        payload["service_km"] = fallback_service_km

    manual_interval_days = to_int(data.get("intervalo_dias"))
    manual_interval_km = to_int(data.get("intervalo_km"))
    if manual_interval_days is not None:
        payload["interval_days"] = manual_interval_days
    if manual_interval_km is not None:
        payload["interval_km"] = manual_interval_km

    if payload.get("interval_days"):
        payload["next_due_date"] = payload["service_date"] + timedelta(days=payload["interval_days"])
    else:
        payload["next_due_date"] = None

    if payload.get("service_km") is not None and payload.get("interval_km"):
        payload["next_due_km"] = payload["service_km"] + payload["interval_km"]
    else:
        payload["next_due_km"] = None

    parser_metadata = payload.get("parser_metadata") or {}
    parser_metadata["manual_overrides"] = {
        "data_servico": data.get("data_servico") is not None,
        "custo": data.get("custo") is not None,
        "quilometragem_servico": data.get("quilometragem_servico") is not None,
        "intervalo_dias": data.get("intervalo_dias") is not None,
        "intervalo_km": data.get("intervalo_km") is not None,
    }
    payload["parser_metadata"] = parser_metadata
    return payload


def _to_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return parse_date_input(value)


def format_date_br(value):
    dt = _to_date(value)
    if not dt:
        return None
    return dt.strftime("%d/%m/%Y")


def serialize_maintenance_row(row):
    if not row:
        return row
    data = dict(row)
    for field in ("service_date", "next_due_date", "created_at"):
        raw = data.get(field)
        if isinstance(raw, datetime):
            data[field] = raw.isoformat()
        elif isinstance(raw, date):
            data[field] = raw.isoformat()

    if isinstance(data.get("cost"), Decimal):
        data["cost"] = float(data["cost"])

    metadata = data.get("parser_metadata")
    if isinstance(metadata, str):
        try:
            data["parser_metadata"] = json.loads(metadata)
        except json.JSONDecodeError:
            data["parser_metadata"] = {}
    elif metadata is None:
        data["parser_metadata"] = {}

    return data


def consolidate_active_maintenance_records(rows):
    if not rows:
        return []

    prepared = [serialize_maintenance_row(row) for row in rows]

    def sort_key(row):
        service = _to_date(row.get("service_date")) or date.min
        created_raw = row.get("created_at")
        if isinstance(created_raw, str):
            try:
                created_dt = datetime.fromisoformat(created_raw)
            except ValueError:
                created_dt = datetime.min
        elif isinstance(created_raw, datetime):
            created_dt = created_raw
        else:
            created_dt = datetime.min
        return service, created_dt, row.get("id", 0)

    prepared.sort(key=sort_key, reverse=True)

    latest_by_type = {}
    custom_records = []
    for row in prepared:
        record_type = row.get("maintenance_type") or "manutencao_geral"
        key = (row.get("vehicle_id"), record_type)

        if record_type == "manutencao_geral":
            if row.get("next_due_date") or row.get("next_due_km"):
                custom_records.append(row)
            continue

        if key not in latest_by_type:
            latest_by_type[key] = row

    return list(latest_by_type.values()) + custom_records


def _status_from_remaining(days_remaining=None, km_remaining=None):
    overdue = False
    warning = False

    # Regras de Tempo (7 dias para aviso)
    if days_remaining is not None:
        if days_remaining < 0:
            overdue = True
        elif days_remaining <= 7:
            warning = True

    # Regras de KM (1000 km para aviso)
    if km_remaining is not None:
        if km_remaining < 0:
            # Trava de segurança: Se o KM venceu mas a data ainda está a mais de 60 dias,
            # tratamos apenas como "Aviso" em vez de "Atenção" (Vermelho).
            if days_remaining is not None and days_remaining > 60:
                warning = True
            else:
                overdue = True
        elif km_remaining <= 1000:
            warning = True

    if overdue:
        return "Atencao", "overdue"
    if warning:
        return "Aviso", "due_soon"
    return "Ok", "on_track"


def _build_message(next_due_date=None, days_remaining=None, next_due_km=None, km_remaining=None):
    parts = []
    if next_due_date:
        if days_remaining is None:
            parts.append(f"Retorno previsto para {format_date_br(next_due_date)}.")
        elif days_remaining < 0:
            parts.append(f"Atrasado ha {abs(days_remaining)} dia(s), previsto para {format_date_br(next_due_date)}.")
        elif days_remaining == 0:
            parts.append(f"Vence hoje ({format_date_br(next_due_date)}).")
        else:
            parts.append(f"Faltam {days_remaining} dia(s), previsto para {format_date_br(next_due_date)}.")

    if next_due_km is not None:
        if km_remaining is None:
            parts.append(f"Retorno previsto aos {next_due_km} km.")
        elif km_remaining < 0:
            parts.append(f"Atrasado por {abs(km_remaining)} km (meta: {next_due_km} km).")
        elif km_remaining == 0:
            parts.append(f"Vence no km atual ({next_due_km} km).")
        else:
            parts.append(f"Faltam {km_remaining} km ate o retorno ({next_due_km} km).")

    if not parts:
        return "Sem previsao de retorno automatica."
    return " ".join(parts)


def build_maintenance_alerts(records, vehicle_km_map=None, reference_date=None):
    if not records:
        return []

    today = reference_date or date.today()
    vehicle_km_map = vehicle_km_map or {}
    alerts = []

    for row in records:
        next_due_date = _to_date(row.get("next_due_date"))
        next_due_km = to_int(row.get("next_due_km"))

        if not next_due_date and next_due_km is None:
            continue

        vehicle_id = row.get("vehicle_id")
        current_km = to_int(vehicle_km_map.get(vehicle_id)) if vehicle_id is not None else None
        days_remaining = (next_due_date - today).days if next_due_date else None
        km_remaining = (next_due_km - current_km) if (next_due_km is not None and current_km is not None) else None
        status, status_code = _status_from_remaining(days_remaining=days_remaining, km_remaining=km_remaining)

        alerts.append(
            {
                "maintenance_id": row.get("id"),
                "vehicle_id": vehicle_id,
                "item": row.get("maintenance_label") or "Manutencao geral",
                "status": status,
                "status_code": status_code,
                "msg": _build_message(
                    next_due_date=next_due_date,
                    days_remaining=days_remaining,
                    next_due_km=next_due_km,
                    km_remaining=km_remaining,
                ),
                "dias_restantes": days_remaining,
                "km_restantes": km_remaining,
                "proxima_data": next_due_date.isoformat() if next_due_date else None,
                "proximo_km": next_due_km,
                "descricao_original": row.get("description"),
            }
        )

    priority = {"overdue": 0, "due_soon": 1, "on_track": 2}
    alerts.sort(
        key=lambda item: (
            priority.get(item.get("status_code"), 3),
            item.get("dias_restantes") if item.get("dias_restantes") is not None else 999999,
            item.get("km_restantes") if item.get("km_restantes") is not None else 999999,
        )
    )
    return alerts
