"""Import de fichiers et suivi d'indexation (US03 ; RM05 à RM11)."""
import io
import json
import os
from datetime import datetime, timedelta, timezone

import pytest
from bson import ObjectId

from app.services.files import CSV_COLUMNS, FileValidationError, inspect_file

ROW = ["2026-11-19T10:42:13.512Z", "ERROR", "transaction", "payment_failed", "payment",
       "Payment gateway timeout after 30s", "504", "30012.4", "ORD-1", "SKU-1", "Casque", "S-1", "U-1",
       "card", "149.9", "TND", "0.1", "196.203.12.45"]
CSV_OK = (",".join(CSV_COLUMNS) + "\n" + ",".join(ROW) + "\n").encode()


def upload(c, name, content, force=False):
    url = "/api/v1/files" + ("?force=true" if force else "")
    return c.post(url, data={"file": (io.BytesIO(content), name)}, content_type="multipart/form-data")


# ---------- validation du contenu ----------
def test_valid_csv():
    _, count, preview = inspect_file(CSV_OK, "csv")
    assert count == 1 and preview[0] == CSV_COLUMNS


def test_csv_bad_header():
    with pytest.raises(FileValidationError) as e:
        inspect_file(b"date,level,msg\n2026-11-19T10:00:00Z,INFO,ok\n", "csv")
    assert "En-tête CSV non conforme" in str(e.value)


def test_csv_missing_required_value():
    bad = ROW.copy(); bad[5] = ""
    with pytest.raises(FileValidationError) as e:
        inspect_file((",".join(CSV_COLUMNS) + "\n" + ",".join(bad)).encode(), "csv")
    assert "message" in e.value.errors[0]


def test_ndjson_with_invalid_line():
    content = b'{"timestamp":"2026-11-19T10:00:00Z","level":"INFO","message":"ok"}\n{pas du json}\n'
    with pytest.raises(FileValidationError) as e:
        inspect_file(content, "json")
    assert e.value.errors == ["Ligne 2 : JSON invalide"]


def test_json_array_is_converted_to_ndjson():
    arr = [{"timestamp": "2026-11-19T10:00:00Z", "level": "info", "message": "a"},
           {"timestamp": "2026-11-19T10:01:00Z", "level": "ERROR", "message": "b"}]
    content, count, _ = inspect_file(json.dumps(arr).encode(), "json")
    assert count == 2 and len(content.decode().strip().splitlines()) == 2


def test_txt_lines():
    good = b"2026-11-19T10:42:13Z ERROR [payment] Payment gateway timeout\n2026-11-19T10:43:00Z INFO [cart] ok\n"
    assert inspect_file(good, "txt")[1] == 2
    with pytest.raises(FileValidationError):
        inspect_file(b"bonjour tout le monde\n", "txt")


def test_empty_and_bad_encoding():
    with pytest.raises(FileValidationError):
        inspect_file(b"   \n", "csv")
    with pytest.raises(FileValidationError) as e:
        inspect_file("é".encode("latin-1"), "txt")
    assert "UTF-8" in str(e.value)


# ---------- endpoint d'import ----------
def test_upload_saves_file_and_metadata(admin_client, app, clients):
    r = upload(admin_client, "transactions.csv", CSV_OK)
    assert r.status_code == 201, r.json
    body = r.json
    assert body["status"] == "pending" and body["expected_count"] == 1
    assert len(body["preview"]) == 2
    stored = os.path.join(app.config["UPLOAD_FOLDER"], f"{body['id']}.csv")
    assert os.path.exists(stored)  # nom = identifiant MongoDB, repris par Logstash dans file_id
    assert clients["db"].files.count_documents({}) == 1


def test_upload_rejects_extension(admin_client):
    r = upload(admin_client, "virus.exe", b"MZ")
    assert r.status_code == 400 and "refusée" in r.json["message"]


def test_upload_reports_errors(admin_client):
    r = upload(admin_client, "bad.json", b'{"level":"INFO"}\n')
    assert r.status_code == 400
    assert "timestamp" in r.json["errors"]["details"][0]


def test_duplicate_upload(admin_client):
    assert upload(admin_client, "a.csv", CSV_OK).status_code == 201
    assert upload(admin_client, "b.csv", CSV_OK).status_code == 409
    assert upload(admin_client, "b.csv", CSV_OK, force=True).status_code == 201


def test_client_cannot_upload(client_user):
    assert upload(client_user, "a.csv", CSV_OK).status_code == 403


# ---------- suivi du statut ----------
def test_status_becomes_indexed(admin_client, clients):
    fid = upload(admin_client, "a.csv", CSV_OK).json["id"]
    clients["es"].counts = {"_csvparsefailure": 0, fid: 1}
    r = admin_client.get(f"/api/v1/files/{fid}")
    assert r.json["status"] == "indexed" and r.json["logs_count"] == 1


def test_status_failed_after_timeout(admin_client, clients):
    fid = upload(admin_client, "a.csv", CSV_OK).json["id"]
    old = datetime.now(timezone.utc) - timedelta(minutes=15)
    clients["db"].files.update_one({"_id": ObjectId(fid)}, {"$set": {"uploaded_at": old, "last_change_at": old}})
    assert admin_client.get(f"/api/v1/files/{fid}").json["status"] == "failed"


def test_list_files(admin_client):
    upload(admin_client, "a.csv", CSV_OK)
    r = admin_client.get("/api/v1/files?status=pending")
    assert r.json["total"] == 1 and "preview" not in r.json["results"][0]
