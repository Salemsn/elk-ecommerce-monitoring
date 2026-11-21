"""Recherche, cache Redis, historique et statistiques (US04 à US07, US13 ; RM12, RM13, RM16)."""
from datetime import datetime, timezone

from app.services.search import build_query


def test_build_query_without_filters():
    assert build_query({}) == {"match_all": {}}


def test_build_query_with_filters():
    q = build_query({"q": "timeout", "level": ["error", "CRITICAL"], "service": "payment",
                     "date_from": datetime(2026, 11, 1, tzinfo=timezone.utc)})
    filters = q["bool"]["filter"]
    assert {"terms": {"level": ["ERROR", "CRITICAL"]}} in filters
    assert {"term": {"service": "payment"}} in filters
    assert {"range": {"@timestamp": {"gte": "2026-11-01T00:00:00+00:00"}}} in filters
    assert q["bool"]["must"][0]["simple_query_string"]["query"] == "timeout"


def test_client_is_restricted_to_allowed_categories():
    q = build_query({}, allowed_categories=["transaction"])
    assert {"terms": {"category": ["transaction"]}} in q["bool"]["filter"]


def test_search_endpoint_and_default_sort(admin_client, clients):
    r = admin_client.get("/api/v1/logs?q=timeout&level=ERROR")
    assert r.status_code == 200
    body = r.json
    assert body["total"] == 1 and body["results"][0]["message"].startswith("Payment")
    assert body["results"][0]["timestamp"] == "2026-11-19T10:42:13.512Z"
    kwargs = [c for c in clients["es"].calls if c[0] == "search"][-1][1]
    assert kwargs["sort"][0] == {"@timestamp": {"order": "desc"}}  # RM13
    assert kwargs["size"] == 50 and kwargs["from_"] == 0


def test_search_is_cached_in_redis(admin_client, clients):
    first = admin_client.get("/api/v1/logs?service=payment").json
    second = admin_client.get("/api/v1/logs?service=payment").json
    assert first["cached"] is False and second["cached"] is True
    assert len([c for c in clients["es"].calls if c[0] == "search"]) == 1


def test_search_history_saved(admin_client):
    admin_client.get("/api/v1/logs?q=timeout")
    admin_client.get("/api/v1/logs")  # sans critère : pas d'historique
    hist = admin_client.get("/api/v1/search-history").json
    assert len(hist) == 1 and hist[0]["query"] == "timeout"


def test_invalid_parameters_are_rejected(admin_client):
    assert admin_client.get("/api/v1/logs?level=FATAL").status_code == 422
    assert admin_client.get("/api/v1/logs?size=500").status_code == 422
    assert admin_client.get("/api/v1/logs?page=500&size=50").status_code == 400  # au-delà de 10 000


def test_client_search_sends_category_filter(client_user, clients):
    client_user.get("/api/v1/logs?q=commande")
    kwargs = [c for c in clients["es"].calls if c[0] == "search"][-1][1]
    assert {"terms": {"category": ["transaction"]}} in kwargs["query"]["bool"]["filter"]


def test_log_detail_and_404(admin_client, clients):
    assert admin_client.get("/api/v1/logs/abc123").json["id"] == "abc123"
    clients["es"].hits = []
    assert admin_client.get("/api/v1/logs/inconnu").status_code == 404


def test_export_csv(admin_client):
    r = admin_client.get("/api/v1/logs/export?level=ERROR")
    assert r.status_code == 200 and r.mimetype == "text/csv"
    lines = r.data.decode("utf-8-sig").splitlines()
    assert lines[0].startswith("timestamp,level,category")
    assert "Payment gateway timeout" in lines[1]


def test_stats_summary_and_cache(admin_client, clients):
    clients["es"].counts = {"CRITICAL": 431, "gte": 120}
    s1 = admin_client.get("/api/v1/stats/summary").json
    assert s1["errors"] == 431 and s1["logs_today"] == 120 and s1["cached"] is False
    assert admin_client.get("/api/v1/stats/summary").json["cached"] is True


def test_stats_timeline_and_breakdown(admin_client):
    t = admin_client.get("/api/v1/stats/timeline?interval=hour&days=1").json
    assert t["points"][0] == {"date": "2026-11-19T00:00:00.000Z", "logs": 10, "errors": 2}
    b = admin_client.get("/api/v1/stats/breakdown").json
    assert b["top_errors"][0]["key"].startswith("Payment")


def test_health(client, clients):
    clients["redis"].info = lambda section=None: {"used_memory_human": "1M"}  # INFO absent de fakeredis
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json["status"] == "healthy"


def test_health_degraded_when_a_service_is_down(client, clients):
    def boom():
        raise ConnectionError("redis injoignable")
    clients["redis"].ping = boom
    r = client.get("/health")
    assert r.status_code == 503
    assert r.json["status"] == "degraded" and r.json["checks"]["redis"]["status"] == "down"


def test_openapi_spec_lists_all_endpoints(client):
    spec = client.get("/api/openapi.json").json
    paths = spec["paths"]
    for p in ["/api/v1/auth/login", "/api/v1/logs", "/api/v1/logs/export", "/api/v1/logs/{log_id}",
              "/api/v1/files", "/api/v1/files/{file_id}", "/api/v1/stats/summary", "/api/v1/users",
              "/api/v1/search-history"]:
        assert p in paths, p
    assert client.get("/api/docs").status_code == 200
