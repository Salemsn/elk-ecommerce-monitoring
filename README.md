# E-Commerce Log Monitoring and Analytics Platform

Plateforme de collecte, d'indexation, de recherche et de visualisation des logs d'un site e-commerce
(mini-projet Big Data — Scénario A).

**Stack :** Elasticsearch 8 · Logstash 8 · Kibana 8 · MongoDB 7 · Redis 7 · Flask 3 · Docker Compose

> État : **semaine 1 — analyse et conception.** L'application affiche une page « Hello World » ;
> les fonctionnalités sont développées sprint par sprint (voir le backlog Jira).

## Architecture

![Architecture C4 — conteneurs](docs/diagrammes/C4_Conteneurs.png)

| Service | Rôle | Port |
|---|---|---|
| `webapp` | Application Flask (pages web + API REST) | 8000 |
| `alert-worker` | Évaluation périodique des règles d'alerte | — |
| `elasticsearch` | Indexation et recherche des logs | 9200 |
| `logstash` | Ingestion des fichiers CSV / JSON | 9600 |
| `kibana` | Dashboards | 5601 |
| `mongodb` | Utilisateurs, fichiers, historique, alertes | 27017 |
| `redis` | Cache, sessions, file d'attente | 6379 |

Documentation de conception : [`docs/`](docs/) (cas d'utilisation, C4, déploiement, séquences,
[modèle de données](docs/modele-donnees.md), maquettes).

## Prérequis

- Docker 24+ et Docker Compose 2+
- 4 Go de RAM disponibles pour Docker (Elasticsearch en utilise 1 Go)

## Démarrage

```bash
git clone https://github.com/<votre-compte>/elk-ecommerce-monitoring.git
cd elk-ecommerce-monitoring
cp .env.example .env          # puis adapter les mots de passe
docker compose up -d --build
```

Le premier démarrage télécharge les images (environ 3 Go) : compter 5 à 10 minutes.

## Vérifier que tout fonctionne

```bash
docker compose ps                       # tous les services « running » / « healthy »
curl http://localhost:9200              # Elasticsearch répond
curl http://localhost:8000/health       # {"status": "healthy"}
```

- Application : http://localhost:8000
- Kibana : http://localhost:5601

## Arrêter

```bash
docker compose down        # arrête les conteneurs
docker compose down -v     # arrête et supprime aussi les données (volumes)
```

## Structure du dépôt

```
.
├── docker-compose.yml
├── .env.example
├── webapp/                 # Application Flask + worker d'alerting
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── worker.py
│   └── app/  (templates/, static/)
├── logstash/pipeline/      # Pipelines Logstash (test, puis CSV et JSON)
├── elasticsearch/          # Index template logs-ecommerce-*
├── kibana/                 # Exports des dashboards (NDJSON)
├── scripts/                # Générateur de logs e-commerce (Faker)
├── data/sample/            # Petits fichiers d'exemple
├── uploads/                # Dossier partagé webapp ↔ Logstash (non versionné)
├── tests/
└── docs/                   # Diagrammes, maquettes, modèle de données
```

## Gestion de projet

Backlog et sprints : Jira (projet SCRUM, 7 sprints d'une semaine).
