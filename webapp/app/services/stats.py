"""Statistiques pour la page d'accueil et les tableaux de bord (US06, US07 ; RM14)."""
from datetime import datetime, timezone

from flask import current_app

from ..extensions import db, es
from .cache import cached


def _scope(user):
    if user.allowed_categories is None:
        return []
    return [{"terms": {"category": user.allowed_categories or ["__aucune__"]}}]


def summary(user):
    """Les 4 indicateurs de la page d'accueil."""
    def compute():
        idx = current_app.config["LOGS_INDEX_PATTERN"]
        scope = _scope(user)
        start_of_day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        total = es().count(index=idx, query={"bool": {"filter": scope}})["count"]
        today = es().count(index=idx, query={"bool": {"filter": scope + [
            {"range": {"@timestamp": {"gte": start_of_day.isoformat()}}}]}})["count"]
        errors = es().count(index=idx, query={"bool": {"filter": scope + [
            {"terms": {"level": ["ERROR", "CRITICAL"]}}]}})["count"]
        return {
            "total_logs": total,
            "logs_today": today,
            "errors": errors,
            "files_imported": db().files.count_documents({}),
        }

    return cached("stats", {"kind": "summary", "scope": _scope(user)}, current_app.config["CACHE_TTL_STATS"], compute)


def timeline(user, interval="day", days=30):
    """Nombre de logs et d'erreurs par heure ou par jour."""
    def compute():
        res = es().search(
            index=current_app.config["LOGS_INDEX_PATTERN"],
            size=0,
            query={"bool": {"filter": _scope(user) + [{"range": {"@timestamp": {"gte": f"now-{days}d/d"}}}]}},
            aggs={"per_bucket": {
                "date_histogram": {"field": "@timestamp", "calendar_interval": interval, "min_doc_count": 0},
                "aggs": {"errors": {"filter": {"terms": {"level": ["ERROR", "CRITICAL"]}}}},
            }},
        )
        return [{"date": b["key_as_string"], "logs": b["doc_count"], "errors": b["errors"]["doc_count"]}
                for b in res["aggregations"]["per_bucket"]["buckets"]]

    return cached("stats", {"kind": "timeline", "i": interval, "d": days, "scope": _scope(user)},
                  current_app.config["CACHE_TTL_STATS"], compute)


def breakdown(user):
    """Répartition par niveau, catégorie, service + Top 10 des erreurs (US07)."""
    def compute():
        res = es().search(
            index=current_app.config["LOGS_INDEX_PATTERN"],
            size=0,
            query={"bool": {"filter": _scope(user)}},
            aggs={
                "levels": {"terms": {"field": "level", "size": 10}},
                "categories": {"terms": {"field": "category", "size": 10}},
                "services": {"terms": {"field": "service", "size": 20}},
                "top_errors": {
                    "filter": {"terms": {"level": ["ERROR", "CRITICAL"]}},
                    "aggs": {"messages": {"terms": {"field": "message.raw", "size": 10}}},
                },
            },
        )
        agg = res["aggregations"]
        to_list = lambda buckets: [{"key": b["key"], "count": b["doc_count"]} for b in buckets]
        return {
            "levels": to_list(agg["levels"]["buckets"]),
            "categories": to_list(agg["categories"]["buckets"]),
            "services": to_list(agg["services"]["buckets"]),
            "top_errors": to_list(agg["top_errors"]["messages"]["buckets"]),
        }

    return cached("stats", {"kind": "breakdown", "scope": _scope(user)}, current_app.config["CACHE_TTL_STATS"], compute)
