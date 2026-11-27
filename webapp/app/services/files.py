"""Import des fichiers de logs et suivi de leur indexation (US03 ; RM05 à RM11).

Le fichier validé est déposé dans uploads/<file_id>.<ext>. Logstash le détecte,
l'indexe et renseigne le champ file_id : on peut donc compter les logs indexés
pour chaque fichier et mettre à jour son statut dans MongoDB.
"""
import csv
import hashlib
import io
import json
import os
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from bson import ObjectId
from bson.errors import InvalidId
from flask import current_app

from ..extensions import db, es

# Colonnes attendues dans un CSV (ordre lu par le pipeline Logstash ecommerce-csv)
CSV_COLUMNS = ["timestamp", "level", "category", "event_type", "service", "message",
               "http_status", "response_time_ms", "order_id", "product_id", "product_name",
               "session_id", "user_id", "payment_method", "amount", "currency",
               "fraud_score", "client_ip"]
REQUIRED_FIELDS = ["timestamp", "level", "message"]  # RM07
LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
TXT_LINE = re.compile(r"^(\S+)\s+(DEBUG|INFO|WARNING|ERROR|CRITICAL)\s+\[([^\]]+)\]\s+(.+)$")
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
PREVIEW_LINES = 10
MAX_REPORTED_ERRORS = 10
PARSE_FAILURE_TAGS = ["_csvparsefailure", "_jsonparsefailure", "_grokparsefailure", "_dateparsefailure"]
FAILED_AFTER = timedelta(minutes=10)
STABLE_AFTER = timedelta(seconds=60)


class FileValidationError(ValueError):
    def __init__(self, message, errors=None, status=400):
        super().__init__(message)
        self.errors = errors or []
        self.status = status


def _now():
    return datetime.now(timezone.utc)


def extension_of(filename):
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def _decode(raw):
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise FileValidationError("Encodage non supporté : le fichier doit être en UTF-8.")


def _check_record(rec, where, errors):
    missing = [f for f in REQUIRED_FIELDS if not str(rec.get(f) or "").strip()]
    if missing:
        errors.append(f"{where} : champ(s) obligatoire(s) manquant(s) : {', '.join(missing)}")
    elif not ISO_DATE.match(str(rec["timestamp"])):
        errors.append(f"{where} : date invalide « {rec['timestamp']} » (format ISO 8601 attendu)")
    elif str(rec["level"]).upper() not in LEVELS:
        errors.append(f"{where} : niveau inconnu « {rec['level']} »")


def inspect_file(raw, ext):
    """Valide le contenu (RM06, RM07) et renvoie (contenu_normalisé, nb_lignes, aperçu).

    Lève FileValidationError avec la liste des erreurs détectées (RM10).
    """
    text = _decode(raw)
    if not text.strip():
        raise FileValidationError("Le fichier est vide.")
    errors, preview, content = [], [], raw

    if ext == "csv":
        rows = list(csv.reader(io.StringIO(text)))
        header = [h.strip() for h in rows[0]]
        if header != CSV_COLUMNS:
            missing = [c for c in CSV_COLUMNS if c not in header]
            detail = f"colonnes manquantes : {', '.join(missing)}" if missing else "ordre des colonnes différent"
            raise FileValidationError(
                "En-tête CSV non conforme (" + detail + ").",
                [f"En-tête attendu : {','.join(CSV_COLUMNS)}"])
        data = [r for r in rows[1:] if any(c.strip() for c in r)]
        for i, row in enumerate(data, start=2):
            if len(row) != len(CSV_COLUMNS):
                errors.append(f"Ligne {i} : {len(row)} colonnes au lieu de {len(CSV_COLUMNS)}")
            else:
                _check_record(dict(zip(CSV_COLUMNS, row)), f"Ligne {i}", errors)
            if len(errors) >= MAX_REPORTED_ERRORS:
                break
        preview = [header] + data[:PREVIEW_LINES]
        count = len(data)

    elif ext == "json":
        stripped = text.lstrip()
        if stripped.startswith("["):  # tableau JSON : converti en une ligne par objet pour Logstash
            try:
                records = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise FileValidationError(f"JSON invalide : {exc.msg} (ligne {exc.lineno})")
            if not all(isinstance(r, dict) for r in records):
                raise FileValidationError("Le tableau JSON doit contenir uniquement des objets.")
            lines = [(i, r) for i, r in enumerate(records, start=1)]
            content = ("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n").encode("utf-8")
        else:
            lines = []
            for i, line in enumerate(text.splitlines(), start=1):
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                    if not isinstance(rec, dict):
                        raise ValueError
                    lines.append((i, rec))
                except ValueError:
                    errors.append(f"Ligne {i} : JSON invalide")
                if len(errors) >= MAX_REPORTED_ERRORS:
                    break
        for i, rec in lines:
            _check_record(rec, f"Ligne {i}", errors)
            if len(errors) >= MAX_REPORTED_ERRORS:
                break
        keys = list(dict.fromkeys(k for _, r in lines[:PREVIEW_LINES] for k in r))
        preview = [keys] + [[str(r.get(k, "")) for k in keys] for _, r in lines[:PREVIEW_LINES]]
        count = len(lines)

    elif ext == "txt":
        parsed = []
        for i, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            m = TXT_LINE.match(line.strip())
            if not m or not ISO_DATE.match(m.group(1)):
                errors.append(f"Ligne {i} : format attendu « AAAA-MM-JJTHH:MM:SSZ NIVEAU [service] message »")
            else:
                parsed.append(list(m.groups()))
            if len(errors) >= MAX_REPORTED_ERRORS:
                break
        preview = [["timestamp", "level", "service", "message"]] + parsed[:PREVIEW_LINES]
        count = len(parsed)
    else:
        raise FileValidationError("Format non supporté.")

    if errors:
        raise FileValidationError(f"{len(errors)} erreur(s) détectée(s) dans le fichier.", errors)
    if count == 0:
        raise FileValidationError("Aucun log trouvé dans le fichier.")
    return content, count, preview


def save_upload(storage, user, force=False):
    """Valide puis enregistre un fichier envoyé par l'administrateur (US03)."""
    filename = os.path.basename(storage.filename or "")
    ext = extension_of(filename)
    allowed = current_app.config["ALLOWED_EXTENSIONS"]
    if ext not in allowed:
        raise FileValidationError(f"Extension « .{ext} » refusée. Formats acceptés : {', '.join(sorted(allowed))}.")
    raw = storage.read()
    max_bytes = current_app.config["MAX_CONTENT_LENGTH"]
    if len(raw) > max_bytes:
        raise FileValidationError(f"Fichier trop volumineux (max {max_bytes // 1024 // 1024} Mo).", status=413)

    content, count, preview = inspect_file(raw, ext)
    sha = hashlib.sha256(raw).hexdigest()
    previous = db().files.find_one({"sha256": sha})
    if previous and not force:
        when = previous["uploaded_at"]
        when = (when.replace(tzinfo=timezone.utc) if when.tzinfo is None else when).astimezone(
            ZoneInfo(current_app.config["TIMEZONE"]))
        raise FileValidationError(
            f"Ce fichier a déjà été importé le {when:%d/%m/%Y à %H:%M} "
            f"(« {previous['original_name']} »). Ajoutez force=true pour le réimporter : "
            "les logs déjà présents ne seront pas dupliqués (RM11).", status=409)

    file_id = ObjectId()
    folder = current_app.config["UPLOAD_FOLDER"]
    incoming = os.path.join(folder, ".incoming")
    os.makedirs(incoming, exist_ok=True)
    tmp_path = os.path.join(incoming, f"{file_id}.part")
    final_path = os.path.join(folder, f"{file_id}.{ext}")
    with open(tmp_path, "wb") as fh:
        fh.write(content)
    os.replace(tmp_path, final_path)  # écriture atomique : Logstash ne voit jamais un fichier incomplet

    doc = {
        "_id": file_id,
        "original_name": filename,
        "stored_name": os.path.basename(final_path),
        "format": ext,
        "size_bytes": len(raw),
        "sha256": sha,
        "uploaded_by": user.id,
        "uploaded_at": _now(),
        "status": "pending",
        "expected_count": count,
        "logs_count": 0,
        "errors_count": 0,
        "status_message": "En attente de traitement par Logstash",
        "preview": preview,
        "last_change_at": _now(),
    }
    db().files.insert_one(doc)
    return doc


def refresh_status(doc):
    """Met à jour le statut d'un fichier en comptant ses logs dans Elasticsearch (SCRUM-37)."""
    if doc["status"] in ("indexed", "failed"):
        return doc
    idx = current_app.config["LOGS_INDEX_PATTERN"]
    fid = str(doc["_id"])
    try:
        count = es().count(index=idx, query={"term": {"file_id": fid}})["count"]
        errors = es().count(index=idx, query={"bool": {"filter": [
            {"term": {"file_id": fid}}, {"terms": {"tags": PARSE_FAILURE_TAGS}}]}})["count"]
    except Exception as exc:
        current_app.logger.warning("Statut du fichier %s non mis à jour : %s", fid, exc)
        return doc

    now = _now()
    uploaded = doc["uploaded_at"].replace(tzinfo=timezone.utc) if doc["uploaded_at"].tzinfo is None else doc["uploaded_at"]
    last_change = doc.get("last_change_at", uploaded)
    last_change = last_change.replace(tzinfo=timezone.utc) if last_change.tzinfo is None else last_change
    update = {"logs_count": count, "errors_count": errors}
    if count != doc.get("logs_count"):
        update["last_change_at"] = now
        last_change = now

    if count >= doc["expected_count"]:
        update.update(status="indexed", status_message="Tous les logs sont indexés", indexed_at=now)
    elif count > 0 and now - last_change > STABLE_AFTER:
        dup = doc["expected_count"] - count
        update.update(status="indexed", indexed_at=now,
                      status_message=f"Indexé ; {dup} ligne(s) identique(s) à des logs existants ignorée(s) (RM11)")
    elif count > 0:
        update.update(status="processing", status_message=f"{count} / {doc['expected_count']} logs indexés")
    elif now - uploaded > FAILED_AFTER:
        update.update(status="failed", status_message="Aucun log indexé après 10 minutes : vérifier les logs Logstash")

    db().files.update_one({"_id": doc["_id"]}, {"$set": update})
    doc.update(update)
    return doc


def list_files(status=None, page=1, size=20):
    query = {"status": status} if status else {}
    total = db().files.count_documents(query)
    docs = list(db().files.find(query, {"preview": 0}).sort("uploaded_at", -1).skip((page - 1) * size).limit(size))
    return total, [refresh_status(d) for d in docs]


def get_file(file_id):
    try:
        doc = db().files.find_one({"_id": ObjectId(file_id)})
    except (InvalidId, TypeError):
        return None
    return refresh_status(doc) if doc else None
