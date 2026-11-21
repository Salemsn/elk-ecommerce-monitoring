"""Contrôle d'accès : connexion obligatoire et rôle administrateur (RM01 à RM04)."""
from functools import wraps

from flask import jsonify, redirect, request, url_for
from flask_login import current_user
from flask_smorest import abort

from .extensions import login_manager


@login_manager.unauthorized_handler
def _unauthorized():
    # API : réponse JSON 401 ; pages web : redirection vers /login
    if request.path.startswith("/api/"):
        return jsonify(code=401, status="Unauthorized", message="Authentification requise"), 401
    return redirect(url_for("auth.login", next=request.full_path))


def login_required_api(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(401, message="Authentification requise")
        return view(*args, **kwargs)
    return wrapper


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(401, message="Authentification requise")
        if not current_user.is_admin:
            abort(403, message="Réservé à l'administrateur")
        return view(*args, **kwargs)
    return wrapper
