"""Application Flask — E-Commerce Log Monitoring."""
import os
import time

import pymongo
import redis
from elasticsearch import Elasticsearch
from flask import Flask, jsonify, render_template


def _check(fn):
    """Exécute un test de dépendance et renvoie son statut et son temps de réponse."""
    start = time.perf_counter()
    try:
        details = fn()
        return {"status": "up", "response_ms": round((time.perf_counter() - start) * 1000, 1), **details}
    except Exception as exc:  # une dépendance en panne ne doit pas faire planter /health
        return {"status": "down", "response_ms": round((time.perf_counter() - start) * 1000, 1), "error": str(exc)[:200]}


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "dev")
    app.config["UPLOAD_FOLDER"] = os.getenv("UPLOAD_FOLDER", "/app/uploads")
    app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("MAX_UPLOAD_MB", "100")) * 1024 * 1024

    es = Elasticsearch(os.getenv("ELASTICSEARCH_URL", "http://elasticsearch:9200"), request_timeout=3)
    mongo = pymongo.MongoClient(os.getenv("MONGO_URI", "mongodb://mongodb:27017"), serverSelectionTimeoutMS=3000)
    cache = redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"), socket_timeout=3)

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/health")
    def health():
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
