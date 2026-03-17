# Système de Gestion et de Vérification des Palmarès Scolaires

## Description
Application web interne centralisant l'historique des résultats scolaires (palmarès).
Transition depuis des archives Excel/Word déstructurées vers une base de données relationnelle
propre, avec outils d'édition en ligne, vérification croisée, fusion de doublons et analytique.

## Stack Technique
- **Backend** : Python 3.12, Django 5.x
- **Base de données** : PostgreSQL (avec extension `pg_trgm` pour la recherche floue)
- **Frontend** : HTML/CSS + HTMX + Alpine.js (pas de SPA classique, pas de React/Vue)
- **Tâches asynchrones** : Celery + Redis
- **Serveur web** : Nginx (reverse proxy, SSL, fichiers statiques)
- **Conteneurisation** : Docker + Docker Compose
- **Export** : PDF (WeasyPrint ou ReportLab), CSV natif Django

## Apps Django prévues
- `core` : configuration globale, base models abstraites, utilitaires
- `accounts` : gestion des utilisateurs et des rôles (RBAC)
- `academics` : Student, AcademicYear, ClassRoom, GradeRecord, SourceFile
- `imports` : ETL, upload Excel, validation dry-run, tâches Celery
- `audit` : AuditLog, middleware de traçabilité
- `dashboard` : vues analytiques, classements, profils étudiants
- `exports` : génération PDF et CSV

## Modèles de données

```
Student          : id, full_name, created_at, updated_at
AcademicYear     : id, label (ex: "2010-2011")
ClassRoom        : id, name (ex: "1ère Année Secondaire A")
GradeRecord      : id, student, classroom, academic_year, percentage, is_verified, verified_by, verified_at
SourceFile       : id, file, academic_year, imported_at, imported_by, status
AuditLog         : id, user, action, model_name, object_id, old_value, new_value, timestamp
```

## Rôles (RBAC)
- **Administrateur** : accès complet, gestion users, purge, audit logs
- **Éditeur** : lecture + écriture, import, fusion doublons, corrections, vérification
- **Lecteur** : lecture seule, recherche, tableaux de bord, export PDF/CSV

## Fonctionnalités clés
1. **Import ETL** : upload Excel/CSV, dry-run avec rapport d'anomalies, barre de progression async
2. **Fusion doublons** : détection et merge d'élèves en double sous un ID unique
3. **Édition inline HTMX** : cellules modifiables à la volée, sauvegarde silencieuse
4. **Réattribution** : détacher un résultat d'un élève pour l'assigner à un autre
5. **Suivi vérification** : marquage visuel des lignes validées
6. **Omnibox** : recherche globale tolérante aux fautes (pg_trgm)
7. **Filtres à facettes** : tri par pourcentage, année, classe
8. **Pagination HTMX** : scroll infini ou pagination dynamique
9. **Tableaux de bord** : moyennes, taux de réussite, courbes d'évolution
10. **Exports** : PDF (relevés, palmarès), CSV filtré
11. **Audit trail** : chaque modification enregistrée avec qui/quand/avant/après
12. **Notifications toast** : retours visuels non-intrusifs

## Conventions de développement
- Langue du code : anglais (variables, fonctions, commentaires)
- Langue de l'UI : français
- Tests obligatoires pour toute logique métier (pytest-django)
- Pas de logique dans les templates — uniquement dans les vues ou services
- Utiliser des class-based views ou des fonctions simples selon le cas (pas de dogme)
- Toujours utiliser `select_related` / `prefetch_related` pour éviter les N+1

## Commandes utiles
```bash
docker compose up -d          # Démarrer tous les services
docker compose exec web python manage.py migrate
docker compose exec web python manage.py createsuperuser
docker compose exec web python manage.py shell
pytest                        # Lancer les tests
celery -A config worker -l info  # Worker Celery (hors Docker pour le dev local)
```

## Variables d'environnement (.env — ne jamais versionner)
```
SECRET_KEY=
DEBUG=
DATABASE_URL=
REDIS_URL=
ALLOWED_HOSTS=
```

## Sécurité
- Fichiers `.env` exclus du versioning (`.gitignore`)
- Seuls les ports 80 et 443 exposés en production via Nginx
- CSRF activé, authentification obligatoire sur toutes les vues
- Les actions sensibles (purge, merge) nécessitent une confirmation explicite

## Structure des fichiers Docker
```
app-palmares/
├── docker-compose.yml
├── docker-compose.prod.yml
├── .env.example
├── Dockerfile
├── nginx/
│   └── nginx.conf
└── palmares/          # Projet Django
    ├── config/        # settings, urls, wsgi, asgi
    └── apps/
        ├── core/
        ├── accounts/
        ├── academics/
        ├── imports/
        ├── audit/
        ├── dashboard/
        └── exports/
```
