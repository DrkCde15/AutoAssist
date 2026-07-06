import os
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

DEMO_MODE = os.getenv("DEMO_MODE", "0") == "1"
DEMO_USER_ID = int(os.getenv("DEMO_USER_ID", "0"))

def is_demo_mode():
    return DEMO_MODE

def get_demo_user_id():
    return DEMO_USER_ID

def demo_vehicle():
    return {
        "id": 1,
        "tipo": "carro",
        "marca": "Volkswagen",
        "modelo": "Gol 1.6",
        "ano_fabricacao": 2020,
        "ano_compra": 2021,
        "quilometragem": 45000,
        "fipe_valor": "R$ 48.000,00",
        "fipe_mes_referencia": "junho/2026",
    }

def demo_maintenance_history():
    return [
        {
            "id": 1,
            "description": "Troca de oleo e filtro realizada na concessionaria",
            "maintenance_type": "troca_oleo",
            "maintenance_label": "Troca de oleo",
            "service_date": (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d"),
            "service_km": 40000,
            "cost": 280.00,
            "next_due_date": (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"),
            "next_due_km": 50000,
        },
        {
            "id": 2,
            "description": "Troca dos pneus dianteiros",
            "maintenance_type": "troca_pneus",
            "maintenance_label": "Troca de pneus",
            "service_date": (datetime.now() - timedelta(days=45)).strftime("%Y-%m-%d"),
            "service_km": 42000,
            "cost": 1200.00,
            "next_due_date": (datetime.now() + timedelta(days=320)).strftime("%Y-%m-%d"),
            "next_due_km": 62000,
        },
        {
            "id": 3,
            "description": "Alinhamento e balanceamento",
            "maintenance_type": "alinhamento",
            "maintenance_label": "Alinhamento e balanceamento",
            "service_date": (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"),
            "service_km": 43000,
            "cost": 150.00,
            "next_due_date": (datetime.now() + timedelta(days=335)).strftime("%Y-%m-%d"),
            "next_due_km": 63000,
        },
    ]

def demo_dashboard():
    return [{
        "veiculo": demo_vehicle(),
        "fipe": {"Valor": "R$ 48.000,00", "MesReferencia": "junho/2026"},
        "saude": [{"item": "Uso Moderado", "msg": "Bom estado, mas fique atento aos prazos de revisao.", "status": "Atencao"}],
        "predicao": {
            "predicted_next_km": 50000,
            "predicted_next_date": (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"),
            "confidence": 0.85,
            "maintenance_type_used": "troca_oleo"
        },
        "estatisticas_extras": {
            "manutencoes_realizadas": 15,
            "data_ultima_manutencao": datetime.now().strftime("%d/%m/%Y"),
            "chats_realizados": 42,
            "health_score": 78,
        },
    }]

def demo_chat_history():
    return [
        {"id": 3, "mensagem_usuario": "Qual oleo usar no Gol 1.6?", "resposta_ia": "Para o VW Gol 1.6 2020, recomendo oleo 5W-40 semissintetico...", "created_at": (datetime.now() - timedelta(hours=2)).isoformat(), "videos": [], "links": [], "topic": "Oleo do motor", "attachments": []},
        {"id": 2, "mensagem_usuario": "Quando trocar a correia dentada?", "resposta_ia": "A correia dentada do Gol 1.6 deve ser trocada a cada 60.000 km ou 5 anos...", "created_at": (datetime.now() - timedelta(days=7)).isoformat(), "videos": [], "links": [], "topic": "Correia dentada", "attachments": []},
        {"id": 1, "mensagem_usuario": "Ola, tudo bem?", "resposta_ia": "Ola! Sou o NOG, consultor automotivo do AutoAssist...", "created_at": (datetime.now() - timedelta(days=14)).isoformat(), "videos": [], "links": [], "topic": "Consultoria Geral", "attachments": []},
    ]

def demo_alerts():
    return [
        {"item": "Troca de oleo", "msg": "Proxima troca em 30 dias ou 50.000 km", "status_code": "due_soon"},
        {"item": "Revisao geral", "msg": "Revisao dos 50.000 km recomendada", "status_code": "due_soon"},
    ]

def demo_user():
    return {
        "id": DEMO_USER_ID or 999,
        "nome": "Usuario Demonstracao",
        "email": "demo@autoassist.app",
        "is_premium": True,
        "possui_veiculo": True,
        "veiculos": [demo_vehicle()],
        "total_consultas": 42,
        "trial_expired": False,
        "trial_days_remaining": 7,
        "is_two_factor_enabled": False,
        "maintenance_email_enabled": True,
    }
