"""Pages web (connexion, accueil). Les écrans complets arrivent au Sprint 5."""
from urllib.parse import urlparse

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from .services import users as users_svc

auth_bp = Blueprint("auth", __name__)
web_bp = Blueprint("web", __name__)


def _safe_next(target):
    """N'accepte qu'une redirection interne (évite les redirections ouvertes)."""
    if target and urlparse(target).netloc == "" and target.startswith("/"):
        return target
    return url_for("web.index")


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


@web_bp.route("/")
@login_required
def index():
    return render_template("index.html")
