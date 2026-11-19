"""Application Flask — E-Commerce Log Monitoring (squelette semaine 1)."""
import os

from flask import Flask, jsonify, render_template


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "dev")
    app.config["UPLOAD_FOLDER"] = os.getenv("UPLOAD_FOLDER", "/app/uploads")
    app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("MAX_UPLOAD_MB", "100")) * 1024 * 1024

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/health")
    def health():
        # Sera complété en semaine 2 : ping Elasticsearch, MongoDB et Redis.
        return jsonify(status="healthy")

    return app
