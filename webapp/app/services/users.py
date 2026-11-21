"""Gestion des comptes (US01, US02, US09 ; RM01 à RM04)."""
import re
from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from pymongo.errors import DuplicateKeyError
from werkzeug.security import check_password_hash, generate_password_hash

from ..extensions import db
from ..models import CATEGORIES, ROLES, User

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class UserError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _now():
    return datetime.now(timezone.utc)


def _oid(user_id):
    try:
        return ObjectId(user_id)
    except (InvalidId, TypeError):
        raise UserError("Utilisateur introuvable", 404)


def _check_password(password):
    if not password or len(password) < 8:
        raise UserError("Le mot de passe doit contenir au moins 8 caractères")


def _check_categories(categories):
    unknown = set(categories or []) - set(CATEGORIES)
    if unknown:
        raise UserError(f"Catégories inconnues : {', '.join(sorted(unknown))}")


def get_user(user_id):
    try:
        doc = db().users.find_one({"_id": ObjectId(user_id)})
    except (InvalidId, TypeError):
        return None
    return User(doc) if doc else None


def authenticate(email, password):
    doc = db().users.find_one({"email": (email or "").strip().lower()})
    if not doc or not check_password_hash(doc["password_hash"], password or ""):
        return None
    if not doc.get("is_active", True):
        raise UserError("Ce compte est désactivé", 403)
    db().users.update_one({"_id": doc["_id"]}, {"$set": {"last_login": _now()}})
    return User(doc)


def create_user(email, password, full_name="", role="client", allowed_categories=None):
    email = (email or "").strip().lower()
    if not EMAIL_RE.match(email):
        raise UserError("Adresse e-mail invalide")
    if role not in ROLES:
        raise UserError("Rôle invalide (admin ou client)")
    _check_password(password)
    if role == "client" and allowed_categories is None:
        allowed_categories = ["transaction", "comportement"]
    _check_categories(allowed_categories)
    doc = {
        "email": email,
        "password_hash": generate_password_hash(password),
        "full_name": full_name.strip(),
        "role": role,
        "allowed_categories": list(CATEGORIES) if role == "admin" else list(allowed_categories),
        "is_active": True,
        "created_at": _now(),
        "last_login": None,
    }
    try:
        doc["_id"] = db().users.insert_one(doc).inserted_id
    except DuplicateKeyError:
        raise UserError("Un compte existe déjà avec cette adresse e-mail", 409)
    return doc


def list_users(role=None):
    query = {"role": role} if role else {}
    return list(db().users.find(query).sort("created_at", -1))


def update_user(user_id, changes, acting_user_id=None):
    oid = _oid(user_id)
    doc = db().users.find_one({"_id": oid})
    if not doc:
        raise UserError("Utilisateur introuvable", 404)
    update = {}
    if "full_name" in changes:
        update["full_name"] = changes["full_name"].strip()
    if "allowed_categories" in changes:
        _check_categories(changes["allowed_categories"])
        update["allowed_categories"] = changes["allowed_categories"]
    if "is_active" in changes:
        if not changes["is_active"] and str(oid) == str(acting_user_id):
            raise UserError("Vous ne pouvez pas désactiver votre propre compte")
        update["is_active"] = bool(changes["is_active"])
    if changes.get("password"):
        _check_password(changes["password"])
        update["password_hash"] = generate_password_hash(changes["password"])
    if update:
        db().users.update_one({"_id": oid}, {"$set": update})
        doc.update(update)
    return doc


def bootstrap_admin(email, password, name):
    """Crée le premier administrateur s'il n'en existe aucun."""
    if db().users.count_documents({"role": "admin"}) == 0:
        try:
            create_user(email, password, name, role="admin")
            return True
        except UserError:
            return False
    return False
