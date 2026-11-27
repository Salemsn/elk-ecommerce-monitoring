"""Configuration de l'application (lue depuis les variables d'environnement / .env)."""
import os


class Config:
    SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-me")

    # Connexions
    ELASTICSEARCH_URL = os.getenv("ELASTICSEARCH_URL", "http://elasticsearch:9200")
    LOGS_INDEX_PATTERN = os.getenv("LOGS_INDEX_PREFIX", "logs-ecommerce") + "-*"
    MONGO_URI = os.getenv("MONGO_URI", "mongodb://mongodb:27017/log_monitoring")
    MONGO_DB = os.getenv("MONGO_DB", "log_monitoring")
    REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

    # Fuseau horaire d'affichage (dates stockées en UTC)
    TIMEZONE = os.getenv("APP_TIMEZONE", "Africa/Tunis")

    # Import de fichiers (RM05, RM06)
    UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", "/app/uploads")
    MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "100"))
    MAX_CONTENT_LENGTH = MAX_UPLOAD_MB * 1024 * 1024
    ALLOWED_EXTENSIONS = {"csv", "json", "txt"}

    # Sessions stockées dans Redis (Flask-Session)
    SESSION_TYPE = "redis"
    SESSION_PERMANENT = True
    PERMANENT_SESSION_LIFETIME = 2 * 3600
    SESSION_KEY_PREFIX = "session:"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    # Cache Redis (secondes)
    CACHE_TTL_SEARCH = int(os.getenv("CACHE_TTL_SEARCH", "60"))
    CACHE_TTL_STATS = int(os.getenv("CACHE_TTL_STATS", "30"))

    # Compte administrateur créé au premier démarrage
    ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@ecommerce.tn")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "Admin@2026")
    ADMIN_NAME = os.getenv("ADMIN_NAME", "Administrateur")

    # Sections affichées dans Swagger UI (« all » pour tout afficher).
    # Les routes non listées fonctionnent normalement mais ne sont pas documentées.
    API_DOCS_SECTIONS = os.getenv("API_DOCS_SECTIONS", "all")

    # Documentation OpenAPI / Swagger (flask-smorest)
    API_TITLE = "E-Commerce Log Monitoring API"
    API_VERSION = "v1"
    OPENAPI_VERSION = "3.0.3"
    OPENAPI_URL_PREFIX = "/api"
    OPENAPI_JSON_PATH = "openapi.json"
    OPENAPI_SWAGGER_UI_PATH = "/docs"
    OPENAPI_SWAGGER_UI_URL = "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/"
    API_SPEC_OPTIONS = {
        "info": {
            "description": (
                "API REST de la plateforme de monitoring des logs e-commerce.\n\n"
                "**Authentification** : connectez-vous d'abord avec `POST /api/v1/auth/login` "
                "(ou via la page /login) ; le cookie de session est ensuite envoyé automatiquement "
                "par Swagger UI. Les routes marquées *admin* exigent le rôle administrateur."
            )
        }
    }
