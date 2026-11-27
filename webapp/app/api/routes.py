"""API REST v1 (SCRUM-39), documentée automatiquement dans Swagger UI (SCRUM-68)."""
import csv
import io

from flask import Response, request
from flask.views import MethodView
from flask_login import current_user, login_user, logout_user
from flask_smorest import Blueprint, abort

from ..security import admin_required, login_required_api
from ..services import files as files_svc
from ..services import search as search_svc
from ..services import stats as stats_svc
from ..services import users as users_svc
from ..services.cache import invalidate
from .schemas import (BreakdownSchema, BusinessQuerySchema, BusinessSchema, FileListQuerySchema, FilePageSchema, FileSchema, HistorySchema,
                      LogPageSchema, LogQuerySchema, LogSchema, LoginSchema, SummarySchema, TimelineQuerySchema,
                      TimelineSchema, UploadQuerySchema, UploadSchema, UserCreateSchema, UserSchema,
                      UserUpdateSchema)

PREFIX = "/api/v1"

auth_blp = Blueprint("Authentification", __name__, url_prefix=f"{PREFIX}/auth",
                     description="Connexion et session (US01, US09)")
logs_blp = Blueprint("Logs", __name__, url_prefix=f"{PREFIX}/logs",
                     description="Recherche, filtres, détail et export CSV des logs (US04, US05, US13)")

files_blp = Blueprint("Fichiers", __name__, url_prefix=f"{PREFIX}/files",
                      description="Import de fichiers et suivi de l'indexation (US03) — admin")
stats_blp = Blueprint("Statistiques", __name__, url_prefix=f"{PREFIX}/stats",
                      description="Indicateurs et agrégations (US06, US07)")
users_blp = Blueprint("Utilisateurs", __name__, url_prefix=f"{PREFIX}/users",
                      description="Gestion des comptes clients (US02) — admin")
history_blp = Blueprint("Historique", __name__, url_prefix=f"{PREFIX}/search-history",
                        description="Historique des recherches de l'utilisateur connecté")


# =============================== Authentification ===============================
@auth_blp.route("/login")
class Login(MethodView):
    @auth_blp.arguments(LoginSchema)
    @auth_blp.response(200, UserSchema)
    @auth_blp.alt_response(401, description="Identifiants incorrects")
    @auth_blp.alt_response(403, description="Compte désactivé")
    def post(self, data):
        """Se connecter (ouvre une session stockée dans Redis)"""
        try:
            user = users_svc.authenticate(data["email"], data["password"])
        except users_svc.UserError as exc:
            abort(exc.status, message=str(exc))
        if not user:
            abort(401, message="E-mail ou mot de passe incorrect")
        login_user(user)
        return user.doc


@auth_blp.route("/logout")
class Logout(MethodView):
    @auth_blp.response(204)
    def post(self):
        """Se déconnecter"""
        logout_user()


@auth_blp.route("/me")
class Me(MethodView):
    @login_required_api
    @auth_blp.response(200, UserSchema)
    def get(self):
        """Utilisateur connecté"""
        return current_user.doc


# =============================== Logs ===============================
CSV_COLUMNS = ["timestamp", "level", "category", "event_type", "service", "message", "http_status",
               "response_time_ms", "order_id", "product_id", "product_name", "payment_method", "amount",
               "currency", "client_ip", "session_id", "user_id"]


def _csv_response(rows):
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return Response("\ufeff" + buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=logs_export.csv"})


@logs_blp.route("")
class Logs(MethodView):
    @login_required_api
    @logs_blp.arguments(LogQuerySchema, location="query")
    @logs_blp.response(200, LogPageSchema)
    def get(self, params):
        """Rechercher, filtrer et exporter les logs

        - `format=json` (par défaut) : 50 logs par page, du plus récent au plus ancien (RM13),
          mis en cache 60 s dans Redis. La première page de chaque recherche avec critères est
          enregistrée dans l'historique (MongoDB).
        - `format=csv` : téléchargement des résultats au format CSV (10 000 lignes maximum).

        Un client ne voit que les catégories autorisées pour son compte (RM16).
        """
        if params.get("format") == "csv":
            return _csv_response(search_svc.export_logs(params, current_user))
        try:
            return search_svc.search_logs(params, current_user)
        except search_svc.SearchError as exc:
            abort(400, message=str(exc))


@logs_blp.route("/<string:log_id>")
class LogDetail(MethodView):
    @login_required_api
    @logs_blp.response(200, LogSchema)
    @logs_blp.alt_response(404, description="Log introuvable")
    def get(self, log_id):
        """Détail d'un log"""
        log = search_svc.get_log(log_id, current_user)
        if not log:
            abort(404, message="Log introuvable")
        return log


# =============================== Fichiers ===============================
@files_blp.route("")
class Files(MethodView):
    @admin_required
    @files_blp.arguments(FileListQuerySchema, location="query")
    @files_blp.response(200, FilePageSchema)
    def get(self, params):
        """Lister les fichiers importés (statut mis à jour à chaque appel)"""
        total, docs = files_svc.list_files(params.get("status"), params["page"], params["size"])
        return {"total": total, "page": params["page"], "size": params["size"], "results": docs}

    @admin_required
    @files_blp.arguments(UploadQuerySchema, location="query")
    @files_blp.arguments(UploadSchema, location="files")
    @files_blp.response(201, FileSchema)
    @files_blp.alt_response(400, description="Fichier invalide (extension, structure, champs obligatoires)")
    @files_blp.alt_response(409, description="Fichier déjà importé")
    @files_blp.alt_response(413, description="Fichier trop volumineux")
    def post(self, query, files):
        """Importer un fichier de logs (CSV, JSON ou TXT)

        Le fichier est validé (RM06, RM07), déposé dans le dossier surveillé par Logstash,
        et ses métadonnées sont enregistrées dans MongoDB avec le statut « pending ».
        La réponse contient un aperçu des 10 premières lignes.
        """
        try:
            doc = files_svc.save_upload(files["file"], current_user, force=query["force"])
        except files_svc.FileValidationError as exc:
            abort(exc.status, message=str(exc), errors={"details": exc.errors})
        invalidate("stats")
        return doc


@files_blp.route("/<string:file_id>")
class FileDetail(MethodView):
    @admin_required
    @files_blp.response(200, FileSchema)
    @files_blp.alt_response(404, description="Fichier introuvable")
    def get(self, file_id):
        """Détail et statut d'indexation d'un fichier"""
        doc = files_svc.get_file(file_id)
        if not doc:
            abort(404, message="Fichier introuvable")
        return doc


# =============================== Statistiques ===============================
@stats_blp.route("/summary")
class Summary(MethodView):
    @login_required_api
    @stats_blp.response(200, SummarySchema)
    def get(self):
        """Les 4 indicateurs de la page d'accueil (cache Redis 30 s)"""
        data, from_cache = stats_svc.summary(current_user)
        return {**data, "cached": from_cache}


@stats_blp.route("/timeline")
class Timeline(MethodView):
    @login_required_api
    @stats_blp.arguments(TimelineQuerySchema, location="query")
    @stats_blp.response(200, TimelineSchema)
    def get(self, params):
        """Évolution du nombre de logs et d'erreurs (par heure ou par jour)"""
        points, from_cache = stats_svc.timeline(current_user, params["interval"], params["days"])
        return {"interval": params["interval"], "points": points, "cached": from_cache}


@stats_blp.route("/breakdown")
class Breakdown(MethodView):
    @login_required_api
    @stats_blp.response(200, BreakdownSchema)
    def get(self):
        """Répartition par niveau, catégorie et service + Top 10 des erreurs"""
        data, from_cache = stats_svc.breakdown(current_user)
        return {**data, "cached": from_cache}


@stats_blp.route("/business")
class Business(MethodView):
    @login_required_api
    @stats_blp.arguments(BusinessQuerySchema, location="query")
    @stats_blp.response(200, BusinessSchema)
    def get(self, params):
        """Indicateurs commerciaux : conversion, commandes, panier moyen, abandons, paiements (US10, US11, US12)"""
        data, from_cache = stats_svc.business(current_user, params["days"])
        return {**data, "cached": from_cache}


# =============================== Utilisateurs ===============================
@users_blp.route("")
class Users(MethodView):
    @admin_required
    @users_blp.response(200, UserSchema(many=True))
    def get(self):
        """Lister les comptes"""
        return users_svc.list_users(request.args.get("role"))

    @admin_required
    @users_blp.arguments(UserCreateSchema)
    @users_blp.response(201, UserSchema)
    @users_blp.alt_response(409, description="E-mail déjà utilisé")
    def post(self, data):
        """Créer un compte client (RM03)"""
        try:
            return users_svc.create_user(**data)
        except users_svc.UserError as exc:
            abort(exc.status, message=str(exc))


@users_blp.route("/<string:user_id>")
class UserDetail(MethodView):
    @admin_required
    @users_blp.arguments(UserUpdateSchema)
    @users_blp.response(200, UserSchema)
    def patch(self, data, user_id):
        """Modifier, activer ou désactiver un compte"""
        try:
            return users_svc.update_user(user_id, data, acting_user_id=current_user.id)
        except users_svc.UserError as exc:
            abort(exc.status, message=str(exc))


# =============================== Historique ===============================
@history_blp.route("")
class History(MethodView):
    @login_required_api
    @history_blp.response(200, HistorySchema(many=True))
    def get(self):
        """Mes 20 dernières recherches"""
        return search_svc.list_history(current_user)


ALL_BLUEPRINTS = [auth_blp, logs_blp, files_blp, stats_blp, users_blp, history_blp]
