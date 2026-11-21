"""Recherche des logs dans Elasticsearch (US04, US05, US13 ; RM12, RM13, RM16)."""
import math
from datetime import datetime, timezone

from flask import current_app

from ..extensions import db, es
from .cache import cached

SORTABLE = ["@timestamp", "level", "service", "category", "event_type", "http_status", "response_time_ms", "amount"]
MAX_WINDOW = 10000  # limite Elasticsearch from + size


class SearchError(ValueError):
    pass


def build_query(params, allowed_categories=None):
    """Construit la requête Elasticsearch (Query DSL) à partir des filtres."""
    filters = []
    if params.get("level"):
        filters.append({"terms": {"level": [lv.upper() for lv in params["level"]]}})
    for field in ("service", "category", "event_type", "payment_method", "file_id"):
        if params.get(field):
            filters.append({"term": {field: params[field]}})
    date_range = {}
    if params.get("date_from"):
        date_range["gte"] = params["date_from"].isoformat()
    if params.get("date_to"):
        date_range["lte"] = params["date_to"].isoformat()
    if date_range:
        filters.append({"range": {"@timestamp": date_range}})
    # Restriction du client aux catégories autorisées (RM04, RM16)
    if allowed_categories is not None:
        filters.append({"terms": {"category": allowed_categories or ["__aucune__"]}})

    must = []
    if params.get("q"):
        must.append({
            "simple_query_string": {
                "query": params["q"],
                "fields": ["message", "order_id", "product_id", "product_name", "session_id", "user_id"],
                "default_operator": "and",
                "lenient": True,
            }
        })
    if not must and not filters:
        return {"match_all": {}}
    return {"bool": {"must": must or [{"match_all": {}}], "filter": filters}}


def _format_hit(hit):
    src = dict(hit["_source"])
    src["id"] = hit["_id"]
    src["index"] = hit.get("_index")
    src["timestamp"] = src.pop("@timestamp", None)
    return src


def search_logs(params, user):
    page, size = params.get("page", 1), params.get("size", 50)
    if (page - 1) * size + size > MAX_WINDOW:
        raise SearchError(f"Pagination limitée aux {MAX_WINDOW} premiers résultats : affinez les filtres.")
    sort_field = params.get("sort", "@timestamp")
    order = params.get("order", "desc")
    query = build_query(params, user.allowed_categories)

    def compute():
        res = es().search(
            index=current_app.config["LOGS_INDEX_PATTERN"],
            query=query,
            sort=[{sort_field: {"order": order}}, {"_doc": "asc"}],
            from_=(page - 1) * size,
            size=size,
            track_total_hits=True,
        )
        total = res["hits"]["total"]["value"]
        return {
            "total": total,
            "page": page,
            "size": size,
            "pages": max(1, math.ceil(min(total, MAX_WINDOW) / size)),
            "took_ms": res.get("took", 0),
            "results": [_format_hit(h) for h in res["hits"]["hits"]],
        }

    cache_payload = {"q": query, "sort": sort_field, "order": order, "page": page, "size": size}
    data, from_cache = cached("search", cache_payload, current_app.config["CACHE_TTL_SEARCH"], compute)
    data["cached"] = from_cache

    has_criteria = any(params.get(k) for k in ("q", "level", "service", "category", "event_type",
                                                "payment_method", "date_from", "date_to"))
    if page == 1 and has_criteria:
        save_history(user, params, data["total"])
    return data


def get_log(log_id, user):
    filters = [{"ids": {"values": [log_id]}}]
    if user.allowed_categories is not None:
        filters.append({"terms": {"category": user.allowed_categories or ["__aucune__"]}})
    res = es().search(index=current_app.config["LOGS_INDEX_PATTERN"], query={"bool": {"filter": filters}}, size=1)
    hits = res["hits"]["hits"]
    return _format_hit(hits[0]) if hits else None


def export_logs(params, user, limit=MAX_WINDOW):
    """Résultats pour l'export CSV (US04), plafonnés à 10 000 lignes."""
    res = es().search(
        index=current_app.config["LOGS_INDEX_PATTERN"],
        query=build_query(params, user.allowed_categories),
        sort=[{params.get("sort", "@timestamp"): {"order": params.get("order", "desc")}}],
        size=limit,
    )
    return [_format_hit(h) for h in res["hits"]["hits"]]


def save_history(user, params, results_count):
    keep = ("level", "service", "category", "event_type", "payment_method", "date_from", "date_to")
    db().search_history.insert_one({
        "user_id": user.id,
        "query": params.get("q", ""),
        "filters": {k: params[k] for k in keep if params.get(k)},
        "results_count": results_count,
        "executed_at": datetime.now(timezone.utc),
    })


def list_history(user, limit=20):
    return list(db().search_history.find({"user_id": user.id}).sort("executed_at", -1).limit(limit))
