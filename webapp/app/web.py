"""Pages web (Sprint 5). Les données sont chargées par les pages via l'API REST /api/v1."""
from functools import wraps
from urllib.parse import urlparse

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from .models import CATEGORIES
from .services import users as users_svc

auth_bp = Blueprint("auth", __name__)
web_bp = Blueprint("web", __name__)


def _safe_next(target):
    """N'accepte qu'une redirection interne (évite les redirections ouvertes)."""
    if target and urlparse(target).netloc == "" and target.startswith("/"):
        return target
    return url_for("web.index")


def admin_page(view):
    @wraps(view)
    @login_required
    def wrapper(*args, **kwargs):
        if not current_user.is_admin:
            abort(403)
        return view(*args, **kwargs)
    return wrapper


# ------------------------------- Connexion -------------------------------
@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("web.index"))
    if request.method == "POST":
        try:
            user = users_svc.authenticate(request.form.get("email"), request.form.get("password"))
        except users_svc.UserError as exc:
            flash(str(exc), "danger")
            return render_template("login.html"), 403
        if not user:
            flash("E-mail ou mot de passe incorrect.", "danger")
            return render_template("login.html"), 401
        login_user(user, remember=bool(request.form.get("remember")))
        return redirect(_safe_next(request.args.get("next")))
    return render_template("login.html")


@auth_bp.route("/logout")
def logout():
    logout_user()
    flash("Vous êtes déconnecté.", "info")
    return redirect(url_for("auth.login"))


# ------------------------------- Pages -------------------------------
@web_bp.route("/")
@login_required
def index():
    if current_user.is_admin:
        return render_template("dashboard.html")
    return render_template("client_dashboard.html")


@web_bp.route("/logs")
@login_required
def logs():
    categories = CATEGORIES if current_user.is_admin else current_user.allowed_categories
    return render_template("logs.html", categories=categories)


@web_bp.route("/historique")
@login_required
def history():
    return render_template("history.html")


@web_bp.route("/import")
@admin_page
def import_page():
    return render_template("import.html")


@web_bp.route("/utilisateurs")
@admin_page
def users():
    return render_template("users.html", categories=CATEGORIES)


# ------------------------------- Erreurs -------------------------------
ERRORS = {
    403: ("Accès refusé", "Cette page est réservée à l'administrateur."),
    404: ("Page introuvable", "La page demandée n'existe pas ou a été déplacée."),
    500: ("Erreur interne", "Une erreur inattendue s'est produite. Réessayez dans quelques instants."),
}


def register_error_pages(app):
    def handler(error):
        code = getattr(error, "code", 500) or 500
        if request.path.startswith("/api/"):
            # réponse JSON détaillée de flask-smorest (message, errors…)
            return current_app.extensions["lm_api"].handle_http_exception(error)
        title, message = ERRORS.get(code, ("Erreur", ""))
        return render_template("404.html", code=code, title=title, message=message), code

    for code in ERRORS:
        app.register_error_handler(code, handler)
