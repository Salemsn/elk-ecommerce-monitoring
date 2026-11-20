"""Générateur de logs e-commerce réalistes (Scénario A).

Produit des fichiers CSV et/ou JSON (une ligne JSON par événement) que Logstash
ingère depuis le dossier uploads/.

Contenu simulé :
  - sessions de navigation : page vue -> produit vu -> ajout au panier
    -> paiement (réussi ou échoué) -> commande, ou abandon de panier ;
  - erreurs applicatives (HTTP 500, timeouts, stock) ;
  - lenteurs d'API (performance) ;
  - événements de sécurité (échecs de connexion, suspicion de fraude) ;
  - trafic plus fort le soir et quelques « pics d'erreurs de paiement »
    pour tester le module d'alerting.

Exemples :
  python generate_logs.py --count 20000 --days 30 --out ../uploads
  python generate_logs.py --count 500 --format csv --out ../data/sample
"""
import argparse
import csv
import json
import os
import random
import uuid
from datetime import datetime, timedelta, timezone

from faker import Faker

COLUMNS = ["timestamp", "level", "category", "event_type", "service", "message",
           "http_status", "response_time_ms", "order_id", "product_id", "product_name",
           "session_id", "user_id", "payment_method", "amount", "currency",
           "fraud_score", "client_ip"]

PRODUCTS = [
    ("SKU-1001", "Smartphone Galaxy A55", 1299.0), ("SKU-1002", "Casque Bluetooth X200", 149.9),
    ("SKU-1003", "Ordinateur portable 15 pouces", 2499.0), ("SKU-1004", "Montre connectée Fit 3", 329.0),
    ("SKU-1005", "Machine à café expresso", 459.0), ("SKU-1006", "Aspirateur robot", 899.0),
    ("SKU-1007", "Baskets running", 219.0), ("SKU-1008", "Sac à dos urbain", 89.9),
    ("SKU-1009", "Huile d'olive extra vierge 1 L", 24.5), ("SKU-1010", "Coffret dattes Deglet Nour", 39.0),
    ("SKU-1011", "Tapis berbère 160x230", 690.0), ("SKU-1012", "Parfum 100 ml", 189.0),
    ("SKU-1013", "Console de jeux", 1890.0), ("SKU-1014", "Écran 27 pouces", 799.0),
    ("SKU-1015", "Chargeur rapide USB-C", 49.9), ("SKU-1016", "Livre de cuisine tunisienne", 45.0),
]
PAYMENT_METHODS = [("card", 0.55), ("cash_on_delivery", 0.25), ("d17", 0.10), ("paypal", 0.10)]
PAYMENT_ERRORS = ["Payment gateway timeout after 30s", "Card declined by issuer (insufficient funds)",
                  "3-D Secure authentication failed", "Invalid card number", "Bank API returned HTTP 502"]
APP_ERRORS = [("catalog", 500, "Database connection pool exhausted"),
              ("cart", 500, "Redis timeout while reading cart"),
              ("checkout", 409, "Stock unavailable for product {pid}"),
              ("api-gateway", 503, "Upstream service unavailable"),
              ("catalog", 404, "Product {pid} not found"),
              ("auth", 500, "Token signature verification failed")]
# Poids horaires du trafic (0 h -> 23 h) : creux la nuit, pic en soirée.
HOUR_WEIGHTS = [2, 1, 1, 1, 1, 1, 2, 4, 6, 7, 8, 8, 9, 9, 8, 8, 9, 10, 12, 14, 15, 13, 9, 5]


def pick_weighted(pairs):
    r, acc = random.random(), 0.0
    for value, w in pairs:
        acc += w
        if r <= acc:
            return value
    return pairs[-1][0]


class Generator:
    def __init__(self, days, end, spikes, seed):
        random.seed(seed)
        self.fake = Faker("fr_FR")
        Faker.seed(seed)
        self.start = end - timedelta(days=days)
        self.end = end
        self.users = [f"U-{random.randint(10000, 99999)}" for _ in range(800)]
        self.ips = [self.fake.ipv4_public() for _ in range(600)]
        # Fenêtres de 15 min où les paiements échouent beaucoup plus souvent.
        self.spikes = []
        for _ in range(spikes):
            t = self.random_time()
            self.spikes.append((t, t + timedelta(minutes=15)))
        self.order_seq = 100000

    def random_time(self):
        day = self.start + timedelta(days=random.randrange(max(1, (self.end - self.start).days)))
        hour = random.choices(range(24), weights=HOUR_WEIGHTS)[0]
        t = day.replace(hour=hour, minute=random.randrange(60), second=random.randrange(60),
                        microsecond=random.randrange(1000) * 1000)
        return min(t, self.end - timedelta(seconds=1))

    def in_spike(self, t):
        return any(a <= t <= b for a, b in self.spikes)

    @staticmethod
    def event(t, level, category, event_type, service, message, **kw):
        e = {c: "" for c in COLUMNS}
        e.update(timestamp=t.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z", level=level, category=category,
                 event_type=event_type, service=service, message=message)
        e.update({k: v for k, v in kw.items() if v is not None})
        return e

    def session(self):
        """Une visite complète d'un utilisateur, de la page d'accueil à la commande (ou non)."""
        t = self.random_time()
        sid = "S-" + uuid.uuid4().hex[:8]
        uid = random.choice(self.users) if random.random() < 0.7 else ""
        ip = random.choice(self.ips)
        common = dict(session_id=sid, user_id=uid, client_ip=ip)
        out = []

        def step(seconds):
            nonlocal t
            t += timedelta(seconds=seconds)
            return t

        rt = lambda base: round(random.gauss(base, base * 0.25), 1)
        out.append(self.event(t, "INFO", "comportement", "page_view", "catalog", "Home page viewed",
                              http_status=200, response_time_ms=max(5, rt(120)), **common))
        pid, pname, price = random.choice(PRODUCTS)
        for _ in range(random.randint(1, 4)):
            pid, pname, price = random.choice(PRODUCTS)
            out.append(self.event(step(random.randint(5, 90)), "INFO", "comportement", "product_view", "catalog",
                                  f"Product {pid} viewed", http_status=200, response_time_ms=max(5, rt(150)),
                                  product_id=pid, product_name=pname, **common))
        if random.random() > 0.22:  # ~78 % quittent sans rien ajouter au panier
            return out
        qty = random.choices([1, 1, 1, 2, 3], k=1)[0]
        amount = round(price * qty, 2)
        out.append(self.event(step(random.randint(5, 60)), "INFO", "comportement", "add_to_cart", "cart",
                              f"Product {pid} added to cart (qty {qty})", http_status=201,
                              response_time_ms=max(5, rt(90)), product_id=pid, product_name=pname,
                              amount=amount, currency="TND", **common))
        if random.random() < 0.67:  # abandon de panier
            out.append(self.event(step(random.randint(1200, 3600)), "WARNING", "comportement", "cart_abandoned",
                                  "cart", f"Cart abandoned after {random.randint(20, 60)} min",
                                  product_id=pid, product_name=pname, amount=amount, currency="TND", **common))
            return out
        method = pick_weighted(PAYMENT_METHODS)
        out.append(self.event(step(random.randint(20, 180)), "INFO", "transaction", "checkout_started", "checkout",
                              "Checkout started", http_status=200, response_time_ms=max(5, rt(200)),
                              product_id=pid, product_name=pname, payment_method=method, amount=amount,
                              currency="TND", **common))
        fraud = round(random.betavariate(1.2, 12), 3)
        if random.random() < 0.02:
            fraud = round(random.uniform(0.75, 0.99), 3)
        fail_rate = 0.65 if self.in_spike(t) else 0.06
        if method == "cash_on_delivery":
            fail_rate = 0.01
        self.order_seq += 1
        oid = f"ORD-{self.order_seq}"
        if fraud > 0.8:
            out.append(self.event(step(2), "WARNING", "securite", "fraud_suspected", "payment",
                                  f"Transaction blocked: fraud score {fraud}", http_status=403,
                                  order_id=oid, payment_method=method, amount=amount, currency="TND",
                                  fraud_score=fraud, **common))
            return out
        if random.random() < fail_rate:
            err = random.choice(PAYMENT_ERRORS)
            level = "CRITICAL" if "timeout" in err or "502" in err else "ERROR"
            out.append(self.event(step(random.randint(2, 35)), level, "transaction", "payment_failed", "payment",
                                  err, http_status=random.choice([402, 502, 504]) if level == "CRITICAL" else 402,
                                  response_time_ms=round(random.uniform(800, 30000), 1), order_id=oid,
                                  product_id=pid, product_name=pname, payment_method=method, amount=amount,
                                  currency="TND", fraud_score=fraud, **common))
            return out
        out.append(self.event(step(random.randint(2, 10)), "INFO", "transaction", "payment_success", "payment",
                              f"Payment accepted for order {oid}", http_status=200,
                              response_time_ms=max(50, rt(900)), order_id=oid, product_id=pid,
                              product_name=pname, payment_method=method, amount=amount, currency="TND",
                              fraud_score=fraud, **common))
        out.append(self.event(step(1), "INFO", "transaction", "order_created", "checkout",
                              f"Order {oid} created ({amount} TND)", http_status=201,
                              response_time_ms=max(5, rt(150)), order_id=oid, product_id=pid,
                              product_name=pname, payment_method=method, amount=amount, currency="TND", **common))
        if random.random() < 0.03:
            out.append(self.event(step(random.randint(86400, 5 * 86400)), "INFO", "transaction", "refund_issued",
                                  "payment", f"Refund issued for order {oid}", http_status=200, order_id=oid,
                                  amount=amount, currency="TND", payment_method=method, **common))
        return [e for e in out if e["timestamp"] <= self.end.strftime("%Y-%m-%dT%H:%M:%S.999Z")]

    def noise(self):
        """Événements techniques indépendants des sessions."""
        t = self.random_time()
        ip = random.choice(self.ips)
        r = random.random()
        if r < 0.45:
            svc, code, msg = random.choice(APP_ERRORS)
            pid = random.choice(PRODUCTS)[0]
            return self.event(t, "ERROR" if code >= 500 else "WARNING", "erreur", "app_error", svc,
                              msg.format(pid=pid), http_status=code,
                              response_time_ms=round(random.uniform(30, 5000), 1), client_ip=ip,
                              product_id=pid if "{pid}" in msg else None)
        if r < 0.75:
            svc = random.choice(["catalog", "cart", "checkout", "payment", "api-gateway"])
            ms = round(random.uniform(2000, 9000), 1)
            return self.event(t, "WARNING", "performance", "slow_response", svc,
                              f"Slow response on /api/{svc} ({ms / 1000:.1f}s)", http_status=200,
                              response_time_ms=ms, client_ip=ip)
        if r < 0.95:
            return self.event(t, "WARNING", "securite", "login_failed", "auth",
                              f"Failed login for {self.fake.email()}", http_status=401,
                              response_time_ms=round(random.uniform(40, 200), 1), client_ip=ip)
        return self.event(t, "DEBUG", "performance", "cache_miss", "cart", "Cache miss on cart:summary",
                          response_time_ms=round(random.uniform(1, 15), 1), client_ip=ip)

    def spike_burst(self, start, stop):
        """Rafale de paiements échoués pendant un incident (pour tester l'alerting)."""
        out = []
        for _ in range(random.randint(45, 90)):
            t = start + timedelta(seconds=random.uniform(0, (stop - start).total_seconds()))
            pid, pname, price = random.choice(PRODUCTS)
            self.order_seq += 1
            err = random.choice(PAYMENT_ERRORS[:1] * 3 + PAYMENT_ERRORS[4:])  # surtout des timeouts
            out.append(self.event(t, "CRITICAL", "transaction", "payment_failed", "payment", err,
                                  http_status=random.choice([502, 504]), response_time_ms=round(random.uniform(15000, 30000), 1),
                                  order_id=f"ORD-{self.order_seq}", product_id=pid, product_name=pname,
                                  payment_method=random.choice(["card", "d17", "paypal"]), amount=price,
                                  currency="TND", session_id="S-" + uuid.uuid4().hex[:8],
                                  user_id=random.choice(self.users), client_ip=random.choice(self.ips)))
        return out

    def generate(self, count):
        events = []
        for a, b in self.spikes:
            events.extend(self.spike_burst(a, b))
        while len(events) < count:
            if random.random() < 0.88:
                events.extend(self.session())
            else:
                events.append(self.noise())
        events = events[:count]
        events.sort(key=lambda e: e["timestamp"])
        return events


def main():
    p = argparse.ArgumentParser(description="Génère des logs e-commerce (CSV / JSON).")
    p.add_argument("--count", type=int, default=20000, help="nombre d'événements (défaut : 20000)")
    p.add_argument("--days", type=int, default=30, help="période couverte en jours (défaut : 30)")
    p.add_argument("--format", choices=["csv", "json", "both"], default="both")
    p.add_argument("--out", default="uploads", help="dossier de sortie (défaut : uploads)")
    p.add_argument("--spikes", type=int, default=3, help="nombre de pics d'erreurs de paiement")
    p.add_argument("--seed", type=int, default=42, help="graine aléatoire (résultats reproductibles)")
    a = p.parse_args()

    end = datetime.now(timezone.utc).replace(tzinfo=None)
    gen = Generator(a.days, end, a.spikes, a.seed)
    events = gen.generate(a.count)
    os.makedirs(a.out, exist_ok=True)
    stamp = end.strftime("%Y%m%d_%H%M%S")
    written = []
    if a.format in ("csv", "both"):
        chunk = events if a.format == "csv" else events[: len(events) // 2]
        path = os.path.join(a.out, f"ecommerce_logs_{stamp}.csv")
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS)
            w.writeheader()
            w.writerows(chunk)
        written.append((path, len(chunk)))
    if a.format in ("json", "both"):
        chunk = events if a.format == "json" else events[len(events) // 2:]
        path = os.path.join(a.out, f"ecommerce_logs_{stamp}.json")
        with open(path, "w", encoding="utf-8") as f:
            for e in chunk:
                f.write(json.dumps({k: v for k, v in e.items() if v != ""}, ensure_ascii=False) + "\n")
        written.append((path, len(chunk)))

    levels, cats = {}, {}
    for e in events:
        levels[e["level"]] = levels.get(e["level"], 0) + 1
        cats[e["category"]] = cats.get(e["category"], 0) + 1
    print(f"{len(events)} événements générés du {events[0]['timestamp'][:10]} au {events[-1]['timestamp'][:10]}")
    for path, n in written:
        print(f"  -> {path} ({n} lignes)")
    print("Niveaux    :", dict(sorted(levels.items())))
    print("Catégories :", dict(sorted(cats.items())))
    print("Pics d'erreurs de paiement :", ", ".join(s.strftime("%d/%m %H:%M") for s, _ in gen.spikes))


if __name__ == "__main__":
    main()
