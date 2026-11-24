# Une seule image de base Python 3.12, deux cibles :
#   - collecteur  : dépendances de requirements-v3.txt (aiohttp, psycopg) pour
#                   lancer le collecteur et les tests sans Python 3.12 sur le poste ;
#   - fournisseur : l'API de simulation seule (cible par défaut, la dernière).
# Contexte de construction : novamarket/ (voir compose.yaml et .dockerignore).
FROM python:3.12-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

FROM base AS collecteur
COPY requirements-v3.txt /tmp/requirements-v3.txt
RUN pip install --no-cache-dir --disable-pip-version-check --root-user-action=ignore \
        -r /tmp/requirements-v3.txt \
    && rm /tmp/requirements-v3.txt
# Le code et les données sont montés par Compose dans /work (pas copiés) :
# une modification du collecteur ne demande pas de reconstruire l'image.
WORKDIR /work
ENTRYPOINT ["python", "ingestion/src/collecteur.py"]

FROM base AS fournisseur
WORKDIR /app
COPY ingestion/api/server.py .
USER 65534:65534
CMD ["python", "-u", "server.py"]
