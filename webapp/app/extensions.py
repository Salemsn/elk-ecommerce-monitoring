"""Clients partagés (Elasticsearch, MongoDB, Redis) et extensions Flask."""
import pymongo
import redis
from elasticsearch import Elasticsearch
from flask import current_app
from flask_login import LoginManager

login_manager = LoginManager()


def build_clients(config):
    """Crée les clients réels à partir de la configuration (remplacés par des doubles dans les tests)."""
    mongo = pymongo.MongoClient(config["MONGO_URI"], serverSelectionTimeoutMS=3000)
    return {
        "es": Elasticsearch(config["ELASTICSEARCH_URL"], request_timeout=10),
        "mongo": mongo,
        "db": mongo[config["MONGO_DB"]],
        "redis": redis.from_url(config["REDIS_URL"], socket_timeout=3),
    }


def es():
    return current_app.extensions["es"]


def db():
    return current_app.extensions["db"]


def cache_client():
    return current_app.extensions["redis"]


def ensure_indexes(database):
    """Index MongoDB (voir docs/modele-donnees.md)."""
    database.users.create_index("email", unique=True)
    database.files.create_index([("uploaded_at", pymongo.DESCENDING)])
    database.files.create_index("status")
    database.files.create_index("sha256")
    database.search_history.create_index([("user_id", pymongo.ASCENDING), ("executed_at", pymongo.DESCENDING)])
