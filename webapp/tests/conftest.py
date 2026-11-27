"""Fixtures pytest : l'application tourne avec des doubles de MongoDB (mongomock),
Redis (fakeredis) et Elasticsearch (FakeES), sans aucun conteneur."""
import os
import sys

import fakeredis
import mongomock
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from app.services import users as users_svc  # noqa: E402


class FakeCluster:
    def health(self):
        return {"status": "yellow"}


class FakeES:
    """Double d'Elasticsearch : enregistre les requêtes et renvoie des réponses prévues."""

    def __init__(self):
        self.calls = []
        self.cluster = FakeCluster()
        self.counts = {}
        self.hits = [{
            "_id": "abc123", "_index": "logs-ecommerce-2026.11",
            "_source": {"@timestamp": "2026-11-19T10:42:13.512Z", "level": "ERROR", "category": "transaction",
                        "event_type": "payment_failed", "service": "payment",
                        "message": "Payment gateway timeout after 30s", "amount": 149.9, "order_id": "ORD-1"},
        }]

    def search(self, **kwargs):
        self.calls.append(("search", kwargs))
        if kwargs.get("size") == 0:
            buckets = [{"key": "ERROR", "doc_count": 3}]
            return {"aggregations": {
                "per_bucket": {"buckets": [{"key_as_string": "2026-11-19T00:00:00.000Z", "doc_count": 10,
                                            "errors": {"doc_count": 2}}]},
                "levels": {"buckets": buckets}, "categories": {"buckets": buckets},
                "services": {"buckets": buckets},
                "top_errors": {"messages": {"buckets": [{"key": "Payment gateway timeout after 30s", "doc_count": 3}]}},
                # indicateurs commerciaux
                "visits": {"doc_count": 1000, "n": {"value": 1000}},
                "carts": {"doc_count": 250, "n": {"value": 220}},
                "checkouts": {"doc_count": 80, "n": {"value": 75}},
                "abandons": {"doc_count": 170},
                "pay_ok": {"doc_count": 66, "avg_ms": {"value": 912.4}},
                "pay_ko": {"doc_count": 6},
                "orders": {"doc_count": 66, "revenue": {"value": 25000.5}, "basket": {"value": 378.8},
                           "methods": {"buckets": [{"key": "card", "doc_count": 40}]},
                           "per_hour": {"buckets": [{"key_as_string": "20", "doc_count": 5},
                                                    {"key_as_string": "20", "doc_count": 3},
                                                    {"key_as_string": "09", "doc_count": 2}]},
                           "per_day": {"buckets": [{"key_as_string": "2026-11-19", "doc_count": 7,
                                                    "revenue": {"value": 2100.0}}]}},
            }}
        return {"took": 4, "hits": {"total": {"value": len(self.hits)}, "hits": self.hits}}

    def count(self, **kwargs):
        self.calls.append(("count", kwargs))
        q = str(kwargs.get("query"))
        for needle, value in self.counts.items():
            if needle in q:
                return {"count": value}
        return {"count": 0}


@pytest.fixture
def clients():
    mongo = mongomock.MongoClient()
    return {"es": FakeES(), "mongo": mongo, "db": mongo["test"], "redis": fakeredis.FakeRedis()}


@pytest.fixture
def app(clients, tmp_path):
    return create_app({
        "TESTING": True,
        "SESSION_TYPE": None,  # cookie de session Flask classique pendant les tests
        "SECRET_KEY": "test",
        "UPLOAD_FOLDER": str(tmp_path),
        "ADMIN_EMAIL": "admin@test.tn",
        "ADMIN_PASSWORD": "Admin@2026",
    }, clients=clients)


@pytest.fixture
def client(app):
    return app.test_client()


def login(client, email, password):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


@pytest.fixture
def admin_client(client):
    assert login(client, "admin@test.tn", "Admin@2026").status_code == 200
    return client


@pytest.fixture
def client_user(app):
    with app.app_context():
        users_svc.create_user("client@test.tn", "Client@2026", "Boutique", "client", ["transaction"])
    c = app.test_client()
    assert login(c, "client@test.tn", "Client@2026").status_code == 200
    return c
