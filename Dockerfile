# ── Étape 1 : compilation des assets front (Tailwind) ─────────────
FROM node:25-alpine AS assets
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci
COPY tailwind.config.js ./
COPY assets ./assets
COPY scripts ./scripts
# Tailwind lit les classes utilisées dans les templates et le code Python
COPY templates ./templates
COPY apps ./apps
RUN npm run build

# ── Étape 2 : application Django ──────────────────────────────────
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dépendances système : WeasyPrint (pango/harfbuzz), netcat (attente de PostgreSQL), gosu
RUN apt-get update && apt-get install -y --no-install-recommends \
    netcat-openbsd \
    libglib2.0-0 \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libharfbuzz-subset0 \
    libgdk-pixbuf-2.0-0 \
    shared-mime-info \
    fonts-liberation \
    curl \
    gosu \
    && rm -rf /var/lib/apt/lists/*

# pip lui-même est mis à jour (des failles sont corrigées dans les versions récentes)
ARG INSTALL_DEV=false
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && if [ "$INSTALL_DEV" = "true" ]; then pip install --no-cache-dir -r requirements-dev.txt; fi

COPY . .
# CSS compilé et bibliothèques JS générés à l'étape 1
COPY --from=assets /build/static/css/app.css /app/static/css/app.css
COPY --from=assets /build/static/js/htmx.min.js /app/static/js/htmx.min.js

RUN mkdir -p /app/logs /app/media /app/staticfiles

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Utilisateur non-root pour l'exécution
# Dossier personnel réel : sans lui fontconfig (WeasyPrint) ne peut pas mettre ses polices en cache
# et les PDF sont régénérés beaucoup plus lentement.
RUN addgroup --system appgroup && adduser --system --ingroup appgroup --home /home/appuser appuser \
    && chown -R appuser:appgroup /app /home/appuser

# L'entrypoint démarre en root pour fixer les permissions des volumes,
# puis bascule sur appuser via gosu.
ENTRYPOINT ["/entrypoint.sh"]
