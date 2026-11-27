"""Application Flask — E-Commerce Log Monitoring."""
import time

from flask import Flask, jsonify
from flask_session import Session

from .config import Config
from flask_smorest import Api

from .extensions import build_clients, ensure_indexes, login_manager


def _check(fn):
    """Exécute un test de dépendance et renvoie son statut et son temps de réponse."""
    start = time.perf_counter()
    try:
        details = fn()
        return {"status": "up", "response_ms": round((time.perf_counter() - start) * 1000, 1), **details}
    except Exception as exc:  # une dépendance en panne ne doit pas faire planter /health
        return {"status": "down", "response_ms": round((time.perf_counter() - start) * 1000, 1), "error": str(exc)[:200]}


def create_app(test_config=None, clients=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)

    clients = clients or build_clients(app.config)
    app.extensions.update(clients)

    # Sessions dans Redis (RM01) ; désactivable pour les tests
    if app.config.get("SESSION_TYPE") == "redis":
        app.config["SESSION_REDIS"] = clients["redis"]
        Session(app)

    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Veuillez vous connecter."
    login_manager.login_message_category = "info"

    from . import security  # noqa: F401  (gestionnaire 401)
    from .api.routes import ALL_BLUEPRINTS
    from .services.users import bootstrap_admin, get_user
    from .web import auth_bp, register_error_pages, web_bp

    login_manager.user_loader(get_user)

    api = Api(app)
    app.extensions["lm_api"] = api
    sections = app.config.get("API_DOCS_SECTIONS", "all")
    documented = None if sections.strip().lower() == "all" else {s.strip() for s in sections.split(",")}
    for blp in ALL_BLUEPRINTS:
        if documented is None or blp.name in documented:
            api.register_blueprint(blp)   # route + documentation Swagger
        else:
            app.register_blueprint(blp)   # route active, absente de la documentation
    app.register_blueprint(auth_bp)
    app.register_blueprint(web_bp)
    register_error_pages(app)

    with app.app_context():
        try:
            ensure_indexes(clients["db"])
            if bootstrap_admin(app.config["ADMIN_EMAIL"], app.config["ADMIN_PASSWORD"], app.config["ADMIN_NAME"]):
                app.logger.warning("Compte administrateur créé : %s (changez le mot de passe)", app.config["ADMIN_EMAIL"])
        except Exception as exc:  # MongoDB pas encore prêt : l'application démarre quand même
            app.logger.error("Initialisation MongoDB impossible : %s", exc)

    @app.route("/health")
    def health():
        es, mongo, cache = clients["es"], clients["mongo"], clients["redis"]
        checks = {
            "elasticsearch": _check(lambda: {"cluster_status": es.cluster.health()["status"]}),
            "mongodb": _check(lambda: {"ok": mongo.admin.command("ping")["ok"]}),
            "redis": _check(lambda: {"ping": cache.ping(), "used_memory": cache.info("memory")["used_memory_human"]}),
        }
        down = [name for name, c in checks.items() if c["status"] == "down"]
        if not down:
            status, code = "healthy", 200
        elif len(down) < len(checks):
            status, code = "degraded", 503
        else:
            status, code = "down", 503
        return jsonify(status=status, checks=checks), code

    return app
