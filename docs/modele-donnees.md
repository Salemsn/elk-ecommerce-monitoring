# Modèle de données

La plateforme utilise trois moteurs de stockage, chacun pour ce qu'il fait le mieux :

| Moteur | Rôle | Données |
|---|---|---|
| **Elasticsearch** | Recherche plein texte et agrégations | Les événements de logs (gros volume, en lecture surtout) |
| **MongoDB** | Données applicatives | Utilisateurs, fichiers importés, historique des recherches, règles et alertes |
| **Redis** | Données temporaires et rapides | Cache des requêtes, sessions, file d'attente, limitation de débit |

---

## 1. Elasticsearch — index `logs-ecommerce-*`

- Un index par mois : `logs-ecommerce-2026.11`, `logs-ecommerce-2026.12`… (facilite la rétention).
- Le template est dans `elasticsearch/index-template.json`.
- `dynamic: false` : un champ inconnu n'est pas indexé, ce qui garde le mapping stable.

| Champ | Type | Rôle |
|---|---|---|
| `@timestamp` | date | Date de l'événement (RM07) ; tri par défaut décroissant (RM13) |
| `level` | keyword | DEBUG, INFO, WARNING, ERROR, CRITICAL |
| `category` | keyword | transaction, erreur, comportement, performance, securite (RM08) |
| `event_type` | keyword | order_created, payment_failed, add_to_cart, cart_abandoned, page_view, refund… |
| `service` | keyword | catalog, cart, checkout, payment, auth, api-gateway |
| `message` | text (+ `message.raw` keyword) | Recherche plein texte ; `raw` pour le Top 10 des erreurs |
| `http_status` | integer | 200, 404, 500… |
| `response_time_ms` | float | Performance des API |
| `order_id`, `product_id`, `product_name`, `session_id`, `user_id` | keyword | Identifiants métier (filtres et agrégations) |
| `payment_method` | keyword | card, paypal, cash_on_delivery… |
| `amount` | scaled_float | Montant (2 décimales) |
| `fraud_score` | float | Score de suspicion (0 à 1) |
| `client_ip` | ip | Adresse IP ; enrichie par GeoIP dans `geo.*` |
| `file_id` | keyword | Fichier d'origine (lien avec MongoDB `files`) |
| `tags` | keyword | `_parsefailure`, `suspicious`, etc. (RM10) |

Exemple de document indexé :

```json
{
  "@timestamp": "2026-11-19T10:42:13.512Z",
  "level": "ERROR",
  "category": "transaction",
  "event_type": "payment_failed",
  "service": "payment",
  "message": "Payment gateway timeout after 30s",
  "http_status": 504,
  "response_time_ms": 30012.4,
  "order_id": "ORD-104582",
  "product_id": "SKU-2231",
  "product_name": "Casque Bluetooth X200",
  "user_id": "U-88213",
  "payment_method": "card",
  "amount": 149.90,
  "currency": "TND",
  "client_ip": "196.203.12.45",
  "geo": { "country_name": "Tunisia", "city_name": "Tunis" },
  "file_id": "6740a1f2c9e77b0012ab34cd",
  "tags": ["payment"]
}
```

**Anti-doublons (RM11)** : Logstash calcule une empreinte (`fingerprint`, SHA-256) sur `@timestamp + service + order_id + message`, utilisée comme `_id` du document. Réimporter le même fichier écrase les mêmes documents au lieu de les dupliquer.

---

## 2. MongoDB — base `log_monitoring`

### `users`
```json
{
  "_id": "ObjectId(...)",
  "email": "admin@ecommerce.tn",
  "password_hash": "$2b$12$...",
  "full_name": "Salem Snoussi",
  "role": "admin",
  "allowed_categories": ["transaction", "erreur", "comportement", "performance", "securite"],
  "is_active": true,
  "created_at": "ISODate(2026-11-19T09:00:00Z)",
  "last_login": "ISODate(2026-11-19T10:30:00Z)"
}
```
- `role` : `admin` ou `client` (RM02). `allowed_categories` limite ce qu'un client peut voir (RM04, RM16).
- Index : `email` unique.

### `files`
```json
{
  "_id": "ObjectId(6740a1f2c9e77b0012ab34cd)",
  "original_name": "transactions_novembre.csv",
  "stored_name": "6740a1f2c9e77b0012ab34cd.csv",
  "format": "csv",
  "size_bytes": 2483120,
  "sha256": "9f2c...e1",
  "uploaded_by": "ObjectId(...)",
  "uploaded_at": "ISODate(2026-11-19T10:40:00Z)",
  "status": "indexed",
  "logs_count": 18452,
  "errors_count": 12,
  "preview": [["timestamp", "level", "service", "message"], ["..."]]
}
```
- `status` : `pending` → `processing` → `indexed` ou `failed`.
- `sha256` du fichier : permet d'avertir si le même fichier est réimporté (RM11).
- Index : `uploaded_at` décroissant, `status`.

### `search_history`
```json
{
  "_id": "ObjectId(...)",
  "user_id": "ObjectId(...)",
  "query": "timeout",
  "filters": { "level": ["ERROR", "CRITICAL"], "service": "payment",
               "from": "2026-11-18T00:00:00Z", "to": "2026-11-19T23:59:59Z" },
  "results_count": 312,
  "executed_at": "ISODate(2026-11-19T10:45:00Z)"
}
```
- Index : `(user_id, executed_at)`.

### `alert_rules`
```json
{
  "_id": "ObjectId(...)",
  "name": "Pic d'erreurs de paiement",
  "description": "Plus de 20 paiements échoués en 5 minutes",
  "type": "threshold",
  "query": { "bool": { "filter": [ { "term": { "event_type": "payment_failed" } } ] } },
  "threshold": 20,
  "window": "5m",
  "severity": "critical",
  "cooldown_minutes": 15,
  "channels": ["email", "webhook"],
  "enabled": true,
  "created_by": "ObjectId(...)"
}
```
- `type` : `threshold` (seuil), `pattern` (regex), `absence` (silence), `anomaly` (pic détecté, module I).

### `alerts`
```json
{
  "_id": "ObjectId(...)",
  "rule_id": "ObjectId(...)",
  "type": "threshold",
  "severity": "critical",
  "description": "34 paiements échoués entre 10:40 et 10:45 (seuil : 20)",
  "value": 34,
  "triggered_at": "ISODate(2026-11-19T10:45:05Z)",
  "status": "open",
  "acknowledged_by": null,
  "resolved_at": null,
  "notifications": [ { "channel": "email", "sent_at": "ISODate(...)", "ok": true } ]
}
```
- Contient au minimum type, date, gravité et description (RM19).
- `status` : `open` → `acknowledged` → `resolved`.

---

## 3. Redis — usages et clés

| Usage | Clé | Type | Durée de vie |
|---|---|---|---|
| Cache des recherches | `cache:search:<sha1(requête+filtres+rôle)>` | String (JSON) | 60 s |
| Cache des statistiques d'accueil | `cache:stats:home` | Hash | 30 s |
| Sessions utilisateur | `session:<session_id>` | String (Flask-Session) | 2 h |
| File d'attente d'ingestion | `queue:ingestion` | List (`LPUSH` / `BRPOP`) | — |
| Limitation de débit de l'API | `ratelimit:<user_id>:<minute>` | String (`INCR` + `EXPIRE`) | 60 s |
| Cooldown des alertes | `alert:cooldown:<rule_id>` | String (`SET NX EX`) | durée du cooldown |
| Compteurs temps réel (bonus) | `stats:logs_per_minute` | Sorted Set | 1 h |
