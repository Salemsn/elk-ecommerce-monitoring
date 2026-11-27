"""Schémas marshmallow : validation des paramètres et documentation OpenAPI."""
from datetime import timezone

from flask_smorest.fields import Upload
from marshmallow import Schema, fields, validate

from ..models import CATEGORIES, ROLES
from ..services.search import SORTABLE

LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
FILE_STATUSES = ["pending", "processing", "indexed", "failed"]


class ErrorSchema(Schema):
    code = fields.Int()
    status = fields.Str()
    message = fields.Str()
    errors = fields.Raw()


# ---------- Authentification ----------
class LoginSchema(Schema):
    email = fields.Email(required=True, metadata={"example": "admin@ecommerce.tn"})
    password = fields.Str(required=True, load_only=True, metadata={"example": "Admin@2026"})


class UserSchema(Schema):
    id = fields.Function(lambda d: str(d["_id"]), dump_only=True)
    email = fields.Email()
    full_name = fields.Str()
    role = fields.Str()
    allowed_categories = fields.List(fields.Str())
    is_active = fields.Bool()
    created_at = fields.DateTime()
    last_login = fields.DateTime(allow_none=True)


class UserCreateSchema(Schema):
    email = fields.Email(required=True, metadata={"example": "client@boutique.tn"})
    password = fields.Str(required=True, load_only=True, validate=validate.Length(min=8),
                          metadata={"example": "Client@2026"})
    full_name = fields.Str(load_default="", metadata={"example": "Boutique Carthage"})
    role = fields.Str(load_default="client", validate=validate.OneOf(ROLES))
    allowed_categories = fields.List(fields.Str(validate=validate.OneOf(CATEGORIES)), load_default=None,
                                     metadata={"example": ["transaction", "comportement"]})


class UserUpdateSchema(Schema):
    full_name = fields.Str()
    password = fields.Str(load_only=True, validate=validate.Length(min=8))
    is_active = fields.Bool()
    allowed_categories = fields.List(fields.Str(validate=validate.OneOf(CATEGORIES)))


# ---------- Logs ----------
class LogQuerySchema(Schema):
    q = fields.Str(metadata={"description": "Recherche plein texte (message, n° de commande, produit…)",
                             "example": "timeout"})
    level = fields.List(fields.Str(validate=validate.OneOf(LEVELS)),
                        metadata={"description": "Un ou plusieurs niveaux (paramètre répétable)"})
    service = fields.Str(metadata={"example": "payment"})
    category = fields.Str(validate=validate.OneOf(CATEGORIES))
    event_type = fields.Str(metadata={"example": "payment_failed"})
    payment_method = fields.Str()
    file_id = fields.Str(metadata={"description": "Logs d'un fichier importé"})
    date_from = fields.AwareDateTime(default_timezone=timezone.utc, metadata={"example": "2026-11-01T00:00:00Z"})
    date_to = fields.AwareDateTime(default_timezone=timezone.utc, metadata={"example": "2026-11-30T23:59:59Z"})
    page = fields.Int(load_default=1, validate=validate.Range(min=1))
    size = fields.Int(load_default=50, validate=validate.Range(min=1, max=100))
    sort = fields.Str(load_default="@timestamp", validate=validate.OneOf(SORTABLE))
    order = fields.Str(load_default="desc", validate=validate.OneOf(["asc", "desc"]))
    format = fields.Str(load_default="json", validate=validate.OneOf(["json", "csv"]),
                        metadata={"description": "json : résultats paginés ; csv : téléchargement des résultats "
                                                 "(10 000 lignes max, page et size ignorés)"})


class GeoSchema(Schema):
    country_name = fields.Str()
    city_name = fields.Str()
    location = fields.Dict()


class LogSchema(Schema):
    id = fields.Str()
    index = fields.Str()
    timestamp = fields.Str()
    level = fields.Str()
    category = fields.Str()
    event_type = fields.Str()
    service = fields.Str()
    message = fields.Str()
    http_status = fields.Int()
    response_time_ms = fields.Float()
    order_id = fields.Str()
    product_id = fields.Str()
    product_name = fields.Str()
    session_id = fields.Str()
    user_id = fields.Str()
    payment_method = fields.Str()
    amount = fields.Float()
    currency = fields.Str()
    fraud_score = fields.Float()
    client_ip = fields.Str()
    geo = fields.Nested(GeoSchema)
    tags = fields.List(fields.Str())
    file_id = fields.Str()
    source_file = fields.Str()


class LogPageSchema(Schema):
    total = fields.Int()
    page = fields.Int()
    size = fields.Int()
    pages = fields.Int()
    took_ms = fields.Int()
    cached = fields.Bool(metadata={"description": "true si le résultat vient du cache Redis"})
    results = fields.List(fields.Nested(LogSchema))


class HistorySchema(Schema):
    id = fields.Function(lambda d: str(d["_id"]))
    query = fields.Str()
    filters = fields.Dict()
    results_count = fields.Int()
    executed_at = fields.DateTime()


# ---------- Fichiers ----------
class UploadSchema(Schema):
    file = Upload(required=True, metadata={"description": "Fichier CSV, JSON ou TXT"})


class UploadQuerySchema(Schema):
    force = fields.Bool(load_default=False, metadata={"description": "Réimporter un fichier déjà importé"})


class FileSchema(Schema):
    id = fields.Function(lambda d: str(d["_id"]))
    original_name = fields.Str()
    format = fields.Str()
    size_bytes = fields.Int()
    sha256 = fields.Str()
    uploaded_by = fields.Str()
    uploaded_at = fields.DateTime()
    status = fields.Str(metadata={"enum": FILE_STATUSES})
    status_message = fields.Str()
    expected_count = fields.Int()
    logs_count = fields.Int()
    errors_count = fields.Int()
    indexed_at = fields.DateTime()
    preview = fields.List(fields.List(fields.Str()))


class FileSummarySchema(FileSchema):
    class Meta:
        exclude = ("preview",)


class FileListQuerySchema(Schema):
    status = fields.Str(validate=validate.OneOf(FILE_STATUSES))
    page = fields.Int(load_default=1, validate=validate.Range(min=1))
    size = fields.Int(load_default=20, validate=validate.Range(min=1, max=100))


class FilePageSchema(Schema):
    total = fields.Int()
    page = fields.Int()
    size = fields.Int()
    results = fields.List(fields.Nested(FileSummarySchema))


# ---------- Statistiques ----------
class SummarySchema(Schema):
    total_logs = fields.Int()
    logs_today = fields.Int()
    errors = fields.Int()
    files_imported = fields.Int()
    cached = fields.Bool()


class TimelineQuerySchema(Schema):
    interval = fields.Str(load_default="day", validate=validate.OneOf(["hour", "day"]))
    days = fields.Int(load_default=30, validate=validate.Range(min=1, max=365))


class BucketSchema(Schema):
    key = fields.Str()
    count = fields.Int()


class TimelinePointSchema(Schema):
    date = fields.Str()
    logs = fields.Int()
    errors = fields.Int()


class TimelineSchema(Schema):
    interval = fields.Str()
    cached = fields.Bool()
    points = fields.List(fields.Nested(TimelinePointSchema))


class BreakdownSchema(Schema):
    levels = fields.List(fields.Nested(BucketSchema))
    categories = fields.List(fields.Nested(BucketSchema))
    services = fields.List(fields.Nested(BucketSchema))
    top_errors = fields.List(fields.Nested(BucketSchema))
    cached = fields.Bool()
