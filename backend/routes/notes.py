from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from routes.database import get_db

notes_bp = Blueprint('notes', __name__)

@notes_bp.get('/api/notes')
@notes_bp.get('/notes')
@jwt_required()
def list_notes():
    """Retorna a lista de anotações do usuário autenticado."""
    user_id = get_jwt_identity()
    with get_db() as (cur, _):
        cur.execute(
            "SELECT id, note, created_at FROM maintenance_notes WHERE user_id = %s ORDER BY created_at DESC",
            (user_id,)
        )
        rows = cur.fetchall()
    return jsonify(rows), 200

@notes_bp.post('/api/notes')
@notes_bp.post('/notes')
@jwt_required()
def create_note():
    """Cria uma nova anotação.

    Espera JSON no corpo: {"note": "texto da anotação"}
    """
    user_id = get_jwt_identity()
    data = request.get_json(silent=True) or {}
    note = data.get('note', '').strip()
    if not note:
        return jsonify(error="Note is required"), 400
    with get_db() as (cur, _):
        cur.execute("INSERT INTO maintenance_notes (user_id, note) VALUES (%s, %s)", (user_id, note))
    return jsonify(message="Note added"), 201
