"""Modèle utilisateur pour Flask-Login (les données sont stockées dans MongoDB)."""
from flask_login import UserMixin

CATEGORIES = ["transaction", "erreur", "comportement", "performance", "securite"]
ROLES = ["admin", "client"]


class User(UserMixin):
    def __init__(self, doc):
        self.doc = doc
        self.id = str(doc["_id"])
        self.email = doc["email"]
        self.full_name = doc.get("full_name", "")
        self.role = doc.get("role", "client")
        self.active = doc.get("is_active", True)

    @property
    def is_active(self):
        return self.active

    @property
    def is_admin(self):
        return self.role == "admin"

    @property
    def allowed_categories(self):
        """Catégories de logs visibles (RM04, RM16). L'administrateur voit tout."""
        if self.is_admin:
            return None
        return self.doc.get("allowed_categories") or []
