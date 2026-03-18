# Palmarès Scolaires

Application web interne centralisant l'historique des résultats scolaires (palmarès).
Transition depuis des archives Excel/Word déstructurées vers une base de données relationnelle
propre, avec outils d'édition en ligne, vérification croisée, fusion de doublons et analytique.

## Stack technique

- **Backend** : Python 3.12, Django 5.1
- **Base de données** : PostgreSQL 16 (avec `pg_trgm` pour la recherche floue)
- **Frontend** : HTML/CSS + Tailwind CSS + HTMX + Alpine.js
- **Tâches asynchrones** : Celery + Redis
- **Serveur web** : Nginx (reverse proxy) + Gunicorn
- **Conteneurisation** : Docker + Docker Compose
- **Export** : PDF (WeasyPrint), CSV natif Django

## Fonctionnalités

- Import ETL depuis Excel (.xlsx) avec dry-run et barre de progression
- Recherche floue tolérante aux fautes (PostgreSQL TrigramSimilarity)
- Édition inline HTMX des notes et noms d'élèves
- Fusion de doublons d'élèves
- Vérification croisée des résultats avec traçabilité
- Tableaux de bord analytiques (moyennes, taux de réussite, courbes d'évolution)
- Export PDF et CSV filtré
- Journal d'audit complet (qui/quand/avant/après)
- Gestion des rôles (Administrateur, Éditeur, Lecteur)

## Démarrage rapide (développement)

### Prérequis

- Docker et Docker Compose

### Installation

```bash
# Cloner le dépôt
git clone https://github.com/VOTRE_USER/app-palmares.git
cd app-palmares

# Copier et configurer les variables d'environnement
cp .env.example .env
# Éditer .env : renseigner SECRET_KEY, mots de passe, etc.

# Lancer les services
docker compose up -d

# Créer un super-utilisateur
docker compose exec web python manage.py createsuperuser

# Activer la recherche floue
docker compose exec db psql -U palmares_user -d palmares_db -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
```

L'application est accessible sur `http://localhost:8000`.

### Générer une SECRET_KEY

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

## Déploiement en production

Voir le guide complet dans [DEPLOY.md](DEPLOY.md) pour le déploiement sur un VPS avec Dokploy et un nom de domaine Hostinger.

## Structure du projet

```
app-palmares/
├── config/                 # Configuration Django (settings, urls, wsgi, celery)
│   └── settings/
│       ├── base.py         # Settings partagés
│       ├── dev.py          # Développement
│       └── prod.py         # Production
├── apps/
│   ├── accounts/           # Utilisateurs et rôles (RBAC)
│   ├── academics/          # Élèves, classes, résultats
│   ├── imports/            # ETL, upload Excel, dry-run
│   ├── exports/            # PDF et CSV
│   ├── dashboard/          # Tableaux de bord, recherche, analytics
│   ├── audit/              # Journal d'audit
│   └── core/               # Utilitaires partagés
├── templates/              # Templates Django
├── static/                 # Fichiers statiques personnalisés
├── nginx/                  # Configuration Nginx
├── docker-compose.yml      # Développement
├── docker-compose.prod.yml # Production
├── Dockerfile
└── DEPLOY.md               # Guide de déploiement
```

## Rôles utilisateurs

| Rôle | Accès |
|------|-------|
| **Administrateur** | Accès complet, gestion users, statistiques avancées, audit |
| **Éditeur** | Lecture + écriture, import, fusion doublons, vérification |
| **Lecteur** | Lecture seule, recherche, export PDF/CSV |

## Commandes utiles

```bash
# Développement
docker compose up -d                                    # Démarrer
docker compose exec web python manage.py migrate        # Migrations
docker compose exec web python manage.py createsuperuser # Créer admin
docker compose exec web python manage.py shell          # Shell Django
docker compose logs -f web                              # Logs

# Production
docker compose -f docker-compose.prod.yml up -d         # Démarrer en prod
docker compose -f docker-compose.prod.yml logs -f web   # Logs prod
```

## Licence

Usage interne uniquement.
