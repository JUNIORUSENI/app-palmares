FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Dépendances système (WeasyPrint, PostgreSQL, netcat pour healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    netcat-openbsd \
    libglib2.0-0 \
    libcairo2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libpangoft2-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    shared-mime-info \
    fonts-liberation \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Créer les répertoires nécessaires
RUN mkdir -p /app/logs /app/media /app/staticfiles

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Utilisateur non-root pour la sécurité
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser
RUN chown -R appuser:appgroup /app

# gosu pour drop de privileges dans l'entrypoint
RUN apt-get update && apt-get install -y --no-install-recommends gosu && rm -rf /var/lib/apt/lists/*

# L'entrypoint démarre en root pour fixer les permissions des volumes,
# puis bascule sur appuser via gosu.
ENTRYPOINT ["/entrypoint.sh"]
