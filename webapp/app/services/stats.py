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
                "date_histogram": {"field": "@timestamp", "calendar_interval": interval, "min_doc_count": 0,
                                   "time_zone": current_app.config["TIMEZONE"]},
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


def business(user, days=30):
    """Indicateurs commerciaux pour le tableau de bord client (US10, US11, US12 ; RM15)."""
    tz = current_app.config["TIMEZONE"]

    def compute():
        ev = lambda name: {"term": {"event_type": name}}
        res = es().search(
            index=current_app.config["LOGS_INDEX_PATTERN"],
            size=0,
            query={"bool": {"filter": _scope(user) + [{"range": {"@timestamp": {"gte": f"now-{days}d/d"}}}]}},
            aggs={
                "visits": {"filter": ev("page_view"), "aggs": {"n": {"cardinality": {"field": "session_id"}}}},
                "carts": {"filter": ev("add_to_cart"), "aggs": {"n": {"cardinality": {"field": "session_id"}}}},
                "checkouts": {"filter": ev("checkout_started"), "aggs": {"n": {"cardinality": {"field": "session_id"}}}},
                "abandons": {"filter": ev("cart_abandoned")},
                "pay_ok": {"filter": ev("payment_success"), "aggs": {"avg_ms": {"avg": {"field": "response_time_ms"}}}},
                "pay_ko": {"filter": ev("payment_failed")},
                "orders": {
                    "filter": ev("order_created"),
                    "aggs": {
                        "revenue": {"sum": {"field": "amount"}},
                        "basket": {"avg": {"field": "amount"}},
                        "methods": {"terms": {"field": "payment_method", "size": 10}},
                        "per_hour": {"date_histogram": {"field": "@timestamp", "calendar_interval": "hour",
                                                        "time_zone": tz, "format": "HH"}},
                        "per_day": {"date_histogram": {"field": "@timestamp", "calendar_interval": "day",
                                                       "time_zone": tz, "format": "yyyy-MM-dd", "min_doc_count": 0},
                                    "aggs": {"revenue": {"sum": {"field": "amount"}}}},
                    },
                },
            },
        )
        a = res["aggregations"]
        visits = a["visits"]["n"]["value"]
        carts_sessions = a["carts"]["n"]["value"]
        orders = a["orders"]["doc_count"]
        add_events = a["carts"]["doc_count"]
        pay_ok, pay_ko = a["pay_ok"]["doc_count"], a["pay_ko"]["doc_count"]
        by_hour = [0] * 24  # cumul par heure de la journée (heure locale)
        for b in a["orders"]["per_hour"]["buckets"]:
            by_hour[int(b["key_as_string"])] += b["doc_count"]
        pct = lambda x, y: round(100 * x / y, 1) if y else 0.0
        return {
            "days": days,
            "visits": visits,
            "orders": orders,
            "revenue": round(a["orders"]["revenue"]["value"] or 0, 2),
            "conversion_rate": pct(orders, visits),
            "average_basket": round(a["orders"]["basket"]["value"] or 0, 2),
            "cart_abandonment_rate": pct(a["abandons"]["doc_count"], add_events),
            "payment_failure_rate": pct(pay_ko, pay_ok + pay_ko),
            "avg_payment_ms": round(a["pay_ok"]["avg_ms"]["value"] or 0),
            "orders_by_hour": by_hour,
            "orders_by_day": [{"date": b["key_as_string"], "orders": b["doc_count"],
                               "revenue": round(b["revenue"]["value"] or 0, 2)}
                              for b in a["orders"]["per_day"]["buckets"]],
            "payment_methods": [{"key": b["key"], "count": b["doc_count"]} for b in a["orders"]["methods"]["buckets"]],
            "funnel": [
                {"step": "Visites", "sessions": visits},
                {"step": "Ajout au panier", "sessions": carts_sessions},
                {"step": "Paiement commencé", "sessions": a["checkouts"]["n"]["value"]},
                {"step": "Commande payée", "sessions": orders},
            ],
        }

    return cached("stats", {"kind": "business", "d": days, "scope": _scope(user)},
                  current_app.config["CACHE_TTL_STATS"], compute)
