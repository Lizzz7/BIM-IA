# NEXO OBRA + IA · imagen para el link (Render, Fly.io, Railway, Hugging Face Spaces, IBM Code Engine, Cloud Run)
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Código del panel + primer modelo: el repo del equipo, en solo lectura (sin los .rvt)
ARG NEXO_REPO_URL=https://github.com/Lizzz7/BIM-IA.git
ARG NEXO_REPO_REF=main
RUN git clone --depth 1 --branch ${NEXO_REPO_REF} ${NEXO_REPO_URL} /repo/BIM-IA \
 && rm -rf /repo/BIM-IA/.git && find /repo/BIM-IA -name "*.rvt" -delete
COPY nexo_ia ./nexo_ia
COPY web ./web
COPY servidor.py empaquetar_version.py ./
# /data debe ser un VOLUMEN PERSISTENTE: ahí viven las versiones publicadas y el estado de obra
ENV NEXO_REPO=/repo/BIM-IA NEXO_MODELOS=/data/modelos NEXO_ESTADO=/data/estado NEXO_HOST=0.0.0.0 PORT=8770
# Secretos (se definen en el panel del proveedor, nunca aquí): NEXO_TOKEN, NEXO_TOKEN_ADMIN, NEXO_LLM + clave del proveedor
# Precalcula el ML del modelo del repo al construir: el primer usuario no espera
RUN NEXO_ESTADO=/app/precalc python -c "from nexo_ia import auditor; auditor.auditar()" \
 && mkdir -p /data && cp -r /app/precalc /data/estado
VOLUME ["/data"]
EXPOSE 8770
CMD ["python", "servidor.py"]
