# S5 · Python 3.12 + Java 21 + dépendances (datasets, huggingface_hub, pyspark).
# Alternative au venv local quand Java 21 ou Python 3.12 manquent sur le poste.
# Contexte de construction : novamarket/volumetrie (voir compose.yaml, service volumetrie).
# Le code et les données sont montés dans /work (novamarket/), pas copiés.
FROM python:3.12-slim-trixie@sha256:191083cdf6c7bda8c76158983163ead5d5cf7b77cf3033e805bb0f5296f51b4b
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    JAVA_HOME=/usr/lib/jvm/java-21-openjdk \
    SPARK_LOCAL_IP=127.0.0.1 \
    PYSPARK_PYTHON=python \
    PYSPARK_SUBMIT_ARGS="--driver-memory 1g pyspark-shell"
RUN apt-get update \
    && apt-get install -y --no-install-recommends openjdk-21-jre-headless procps \
    && ln -s "$(dirname "$(dirname "$(readlink -f "$(command -v java)")")")" /usr/lib/jvm/java-21-openjdk \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --disable-pip-version-check --root-user-action=ignore \
        -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt \
    && chmod g+w,o+w /etc/passwd
# Hadoop (sous Spark) exige un nom pour l'UID courant : Compose lance le conteneur
# avec l'UID du poste, absent de /etc/passwd ; l'entrée est ajoutée au démarrage.
COPY --chmod=755 entree.sh /usr/local/bin/entree.sh
ENTRYPOINT ["/usr/local/bin/entree.sh"]
WORKDIR /work
