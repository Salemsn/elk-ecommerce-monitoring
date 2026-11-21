"""Cache Redis des requêtes Elasticsearch (SCRUM-40).

Si Redis est indisponible, l'application continue de fonctionner sans cache.
"""
import hashlib
import json

from flask import current_app

from ..extensions import cache_client


def make_key(namespace, payload):
    raw = json.dumps(payload, sort_keys=True, default=str)
    return f"cache:{namespace}:{hashlib.sha1(raw.encode()).hexdigest()}"


def cached(namespace, payload, ttl, compute):
    """Renvoie (données, depuis_le_cache)."""
    key = make_key(namespace, payload)
    client = cache_client()
    try:
        hit = client.get(key)
        if hit is not None:
            return json.loads(hit), True
    except Exception as exc:  # Redis en panne : on calcule quand même
        current_app.logger.warning("Cache Redis indisponible : %s", exc)
    data = compute()
    try:
        client.setex(key, ttl, json.dumps(data, default=str))
    except Exception:
        pass
    return data, False


def invalidate(namespace):
    """Supprime toutes les entrées d'un espace (ex. statistiques après un import)."""
    try:
        client = cache_client()
        for key in client.scan_iter(match=f"cache:{namespace}:*"):
            client.delete(key)
    except Exception:
        pass
