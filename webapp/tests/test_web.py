"""Pages de l'interface web (Sprint 5) et indicateurs commerciaux."""
from conftest import login


def test_admin_pages_render(admin_client):
    for url, marker in [("/", "Tableau de bord"), ("/logs", "Rechercher dans les logs"),
                        ("/import", "Importer des fichiers"), ("/historique", "Historique des recherches"),
                        ("/utilisateurs", "Comptes utilisateurs")]:
        r = admin_client.get(url)
        assert r.status_code == 200, url
        assert marker in r.get_data(as_text=True), url


def test_client_sees_client_dashboard_and_no_admin_pages(client_user):
    home = client_user.get("/").get_data(as_text=True)
    assert "Mon tableau de bord commercial" in home
    assert "Importation" not in home  # pas de lien d'administration dans le menu
    assert client_user.get("/import").status_code == 403
    assert client_user.get("/utilisateurs").status_code == 403
    logs = client_user.get("/logs").get_data(as_text=True)
    assert 'value="transaction"' in logs and 'value="securite"' not in logs


def test_custom_404_page(admin_client):
    r = admin_client.get("/page-inexistante")
    assert r.status_code == 404 and "Page introuvable" in r.get_data(as_text=True)


def test_api_errors_stay_json(client_user):
    r = client_user.get("/api/v1/users")
    assert r.status_code == 403 and r.json["message"] == "Réservé à l'administrateur"


def test_static_assets_are_served_locally(client):
    for path in ["/static/vendor/bootstrap/bootstrap.min.css", "/static/vendor/chartjs/chart.umd.js",
                 "/static/vendor/bootstrap-icons/fonts/bootstrap-icons.woff2", "/static/js/app.js"]:
        assert client.get(path).status_code == 200, path


def test_business_kpis(client_user):
    b = client_user.get("/api/v1/stats/business?days=30").json
    assert b["conversion_rate"] == 6.6          # 66 commandes / 1000 visites
    assert b["cart_abandonment_rate"] == 68.0   # 170 abandons / 250 ajouts
    assert b["payment_failure_rate"] == 8.3     # 6 / 72
    assert b["average_basket"] == 378.8
    assert b["orders_by_hour"][20] == 8 and b["orders_by_hour"][9] == 2 and len(b["orders_by_hour"]) == 24
    assert b["funnel"][0] == {"step": "Visites", "sessions": 1000}


def test_business_days_validation(admin_client):
    assert admin_client.get("/api/v1/stats/business?days=12").status_code == 422


def test_history_deduplicates_repeated_search(admin_client):
    for _ in range(3):
        admin_client.get("/api/v1/logs?q=timeout&level=ERROR")
    admin_client.get("/api/v1/logs?q=timeout&level=CRITICAL")
    rows = admin_client.get("/api/v1/search-history").json
    assert [(r["query"], r["filters"]) for r in rows] == [
        ("timeout", {"level": ["CRITICAL"]}), ("timeout", {"level": ["ERROR"]})]


def test_history_dates_are_iso(admin_client):
    admin_client.get("/api/v1/logs?q=x&date_from=2026-11-01T00:00:00Z")
    f = admin_client.get("/api/v1/search-history").json[0]["filters"]
    assert f["date_from"] == "2026-11-01T00:00:00Z"
