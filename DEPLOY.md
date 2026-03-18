# Guide de Déploiement — Palmarès Scolaires

Déploiement sur VPS avec **Dokploy** + nom de domaine **Hostinger**.

---

## Prérequis

- Un VPS (Ubuntu 22.04+ recommandé, minimum 2 Go RAM, 1 vCPU)
- Un nom de domaine sur Hostinger
- Accès SSH au VPS (root ou sudo)
- Le code source poussé sur un dépôt Git (GitHub, GitLab, etc.)

---

## Étape 1 : Préparer le dépôt Git

### 1.1 Pousser le code sur GitHub

```bash
# Sur votre machine locale
cd app-palmares
git add -A
git commit -m "Production-ready: sécurité, Docker, Nginx"
git remote add origin https://github.com/VOTRE_USER/app-palmares.git
git push -u origin main
```

> **Important** : Vérifiez que `.env` n'est PAS dans le dépôt (il est dans `.gitignore`).

---

## Étape 2 : Installer Dokploy sur le VPS

### 2.1 Se connecter au VPS

```bash
ssh root@VOTRE_IP_VPS
```

### 2.2 Installer Dokploy

```bash
curl -sSL https://dokploy.com/install.sh | sh
```

L'installation prend 2-3 minutes. À la fin, vous verrez :

```
Dokploy is now running on http://VOTRE_IP_VPS:3000
```

### 2.3 Accéder au panneau Dokploy

1. Ouvrez `http://VOTRE_IP_VPS:3000` dans votre navigateur
2. Créez votre compte administrateur (email + mot de passe)
3. Vous arrivez sur le dashboard Dokploy

---

## Étape 3 : Configurer le domaine sur Hostinger

### 3.1 Ajouter un enregistrement DNS

1. Connectez-vous à [Hostinger](https://hpanel.hostinger.com)
2. Allez dans **Domaines** → votre domaine → **DNS / Nameservers**
3. Ajoutez un enregistrement **A** :
   - **Type** : A
   - **Nom** : `@` (ou `palmares` si vous voulez un sous-domaine `palmares.votre-domaine.com`)
   - **Pointe vers** : `VOTRE_IP_VPS`
   - **TTL** : 3600

4. (Optionnel) Ajoutez aussi un enregistrement pour `www` :
   - **Type** : CNAME
   - **Nom** : `www`
   - **Pointe vers** : `votre-domaine.com`

> **Note** : La propagation DNS peut prendre de 5 minutes à 24 heures.

### 3.2 Vérifier la propagation DNS

```bash
# Depuis n'importe quel terminal
ping votre-domaine.com
# Doit retourner l'IP de votre VPS
```

Ou utilisez : https://dnschecker.org

---

## Étape 4 : Créer le projet dans Dokploy

### 4.1 Créer un nouveau projet

1. Dans Dokploy, cliquez sur **Projects** → **+ Create Project**
2. Nom du projet : `palmares`

### 4.2 Ajouter un service Compose

1. Dans le projet `palmares`, cliquez **+ Create Service**
2. Choisissez **Compose**
3. Nom : `palmares-stack`
4. Source : **Git** → collez l'URL de votre dépôt GitHub
5. Branch : `main`
6. Compose Path : `docker-compose.prod.yml`

### 4.3 Configurer les variables d'environnement

Dans les settings du service Compose, allez dans **Environment** et ajoutez :

```env
# Django
SECRET_KEY=VOTRE_CLE_SECRETE_GENEREE
DEBUG=False
ALLOWED_HOSTS=votre-domaine.com,www.votre-domaine.com
DJANGO_SETTINGS_MODULE=config.settings.prod

# PostgreSQL
DATABASE_URL=postgres://palmares_user:MOT_DE_PASSE_FORT@db:5432/palmares_db
POSTGRES_DB=palmares_db
POSTGRES_USER=palmares_user
POSTGRES_PASSWORD=MOT_DE_PASSE_FORT

# Redis
REDIS_URL=redis://redis:6379/0

# CSRF (important pour HTTPS)
CSRF_TRUSTED_ORIGINS=https://votre-domaine.com,https://www.votre-domaine.com
```

**Pour générer une SECRET_KEY sécurisée** (exécutez sur votre machine) :

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

**Pour générer un mot de passe DB fort** :

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

> **Attention** : Le mot de passe dans `DATABASE_URL` et dans `POSTGRES_PASSWORD` doit être **identique**.

---

## Étape 5 : Configurer le domaine et SSL dans Dokploy

### 5.1 Ajouter le domaine

1. Dans le service Compose, allez dans **Domains**
2. Cliquez **+ Add Domain**
3. **Host** : `votre-domaine.com`
4. **Container Port** : `80` (c'est Nginx qui écoute sur le port 80)
5. **HTTPS** : activé (Dokploy gère automatiquement Let's Encrypt)
6. **Certificate** : Let's Encrypt (automatique)

Si vous voulez aussi `www` :
- Ajoutez un second domaine : `www.votre-domaine.com` → port `80`

### 5.2 Appliquer la configuration

Cliquez **Deploy** pour lancer le premier déploiement.

---

## Étape 6 : Premier déploiement

### 6.1 Surveiller les logs

Dans Dokploy, allez dans **Logs** du service pour suivre le déploiement.

Vous devriez voir :
```
Waiting for PostgreSQL...
PostgreSQL ready.
Running migrations...
Collecting static files...
[INFO] Starting gunicorn...
```

### 6.2 Créer le super-utilisateur

Dans Dokploy, ouvrez un **Terminal** sur le conteneur `web` (ou connectez-vous en SSH au VPS) :

```bash
# Option 1 : Via Dokploy Terminal
# Trouvez le conteneur web et ouvrez un shell

# Option 2 : Via SSH sur le VPS
docker ps  # Trouvez le conteneur web (ex: palmares-stack-web-1)
docker exec -it palmares-stack-web-1 python manage.py createsuperuser
```

Remplissez :
- **Username** : admin
- **Email** : votre-email@example.com
- **Password** : un mot de passe fort

### 6.3 Activer l'extension pg_trgm

Pour que la recherche floue fonctionne :

```bash
docker exec -it palmares-stack-db-1 psql -U palmares_user -d palmares_db -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
```

### 6.4 Vérifier le site

Ouvrez `https://votre-domaine.com` dans votre navigateur.

Vous devriez voir la page de connexion. Connectez-vous avec le super-utilisateur.

---

## Étape 7 : Configurer le rôle admin

Après connexion au site :

1. Allez à `https://votre-domaine.com/admin/`
2. Cliquez sur **Utilisateurs**
3. Ouvrez votre utilisateur
4. Changez le **Rôle** en `Administrateur`
5. Sauvegardez

---

## Étape 8 : Post-déploiement

### 8.1 Vérifications de sécurité

```bash
# Sur le VPS, vérifiez que seuls les ports nécessaires sont ouverts
ss -tlnp
# Seuls les ports 22 (SSH), 80 (HTTP), 443 (HTTPS) et 3000 (Dokploy) doivent être ouverts
```

### 8.2 Sauvegardes automatiques de la base de données

Créez un script de backup sur le VPS :

```bash
cat > /root/backup-palmares.sh << 'SCRIPT'
#!/bin/bash
BACKUP_DIR="/root/backups/palmares"
mkdir -p "$BACKUP_DIR"
DATE=$(date +%Y%m%d_%H%M%S)
CONTAINER=$(docker ps -qf "name=db" --filter "ancestor=postgres:16-alpine" | head -1)

docker exec "$CONTAINER" pg_dump -U palmares_user palmares_db | gzip > "$BACKUP_DIR/palmares_$DATE.sql.gz"

# Garder les 30 derniers backups
ls -tp "$BACKUP_DIR"/*.sql.gz | tail -n +31 | xargs -I {} rm -- {}
echo "Backup done: palmares_$DATE.sql.gz"
SCRIPT

chmod +x /root/backup-palmares.sh
```

Ajoutez un cron pour un backup quotidien :

```bash
crontab -e
# Ajoutez cette ligne :
0 3 * * * /root/backup-palmares.sh >> /var/log/palmares-backup.log 2>&1
```

### 8.3 Restaurer un backup

```bash
CONTAINER=$(docker ps -qf "name=db" --filter "ancestor=postgres:16-alpine" | head -1)
gunzip -c /root/backups/palmares/palmares_YYYYMMDD_HHMMSS.sql.gz | docker exec -i "$CONTAINER" psql -U palmares_user -d palmares_db
```

---

## Étape 9 : Mises à jour futures

### Déploiement automatique

Dans Dokploy, le service peut être configuré pour se redéployer automatiquement à chaque `git push` :

1. Dans le service, allez dans **Settings**
2. Activez **Auto Deploy** sur la branche `main`
3. Ou cliquez manuellement **Redeploy** après chaque push

### Mise à jour manuelle

```bash
# Sur votre machine locale
git add -A
git commit -m "Description des changements"
git push origin main
```

Puis dans Dokploy : **Redeploy**.

### Si vous devez exécuter des migrations manuelles

```bash
docker exec -it palmares-stack-web-1 python manage.py migrate
```

---

## Dépannage

### Le site affiche une erreur 502

- Vérifiez les logs du conteneur `web` dans Dokploy
- Vérifiez que PostgreSQL est prêt : `docker exec palmares-stack-db-1 pg_isready`

### Les fichiers statiques ne s'affichent pas

```bash
docker exec -it palmares-stack-web-1 python manage.py collectstatic --noinput
```

### Erreur CSRF

Vérifiez que `CSRF_TRUSTED_ORIGINS` contient bien `https://votre-domaine.com` (avec `https://`).

### La recherche floue ne fonctionne pas

```bash
docker exec -it palmares-stack-db-1 psql -U palmares_user -d palmares_db -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
```

### Les imports Excel ne fonctionnent pas

Vérifiez que le worker Celery tourne :
```bash
docker logs palmares-stack-celery-1
```

### Voir les logs d'erreur Django

```bash
docker exec -it palmares-stack-web-1 cat /app/logs/django_errors.log
```

---

## Architecture finale

```
Internet
    │
    ▼
[Dokploy Traefik / Let's Encrypt]  ←── HTTPS (port 443)
    │
    ▼
[Nginx]  ←── Port 80 (interne)
    │
    ├── /static/  → fichiers statiques (cache 30j)
    ├── /media/   → fichiers uploadés (cache 7j)
    └── /         → proxy vers Gunicorn
                        │
                        ▼
                  [Gunicorn + Django]
                        │
                  ┌─────┴─────┐
                  ▼           ▼
            [PostgreSQL]  [Redis]
                              │
                              ▼
                        [Celery Worker]
```
