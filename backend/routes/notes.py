from flask import Blueprint, request, jsonify
from routes.database import get_db

notes_bp = Blueprint('notes', __name__)

@notes_bp.get('/notes')
def list_notes():
    """Retorna a lista de anotações armazenadas."""
    with get_db() as (cur, _):
        cur.execute("SELECT id, note, created_at FROM maintenance_notes ORDER BY created_at DESC")
        rows = cur.fetchall()
    return jsonify(rows), 200

@notes_bp.post('/notes')
def create_note():
    """Cria uma nova anotação.

    Espera JSON no corpo: {"note": "texto da anotação"}
    """
    data = request.get_json(silent=True) or {}
    note = data.get('note', '').strip()
    if not note:
        return jsonify(error="Note is required"), 400
    with get_db() as (cur, _):
        cur.execute("INSERT INTO maintenance_notes (note) VALUES (%s)", (note,))
    return jsonify(message="Note added"), 201
