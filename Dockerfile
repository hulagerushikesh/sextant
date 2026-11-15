# The agent server, with the knowledge-base MCP server as its subprocess.
#
# Built on the full python image rather than -slim on purpose: chromadb
# pulls in packages that want a compiler, and trading a
# larger base for a build that works first time is the right way round for
# something people run once to try the project.
FROM python:3.12

# The process runs as this uid, not root. It must match the owner of the
# host directory bind-mounted at /data/chroma (deploy/README B2 chowns it to
# the box user; on the GCE image that is 1001). Override at build time:
#   docker compose build --build-arg APP_UID=1000
ARG APP_UID=1001
RUN useradd --uid "$APP_UID" --create-home --shell /usr/sbin/nologin app

WORKDIR /app

# Dependency install is its own layer, so editing source does not re-resolve
# and re-download it. No torch since milestone 27: both search models run on
# ONNX Runtime, and the image must not ask for the `torch` extra.
COPY pyproject.toml README.md ./
# `.[app]`, not `.` -- and the brackets are the whole deployment. 0.9.0 moved
# fastapi, uvicorn and google-genai out of the base dependencies so that
# `pip install sextant-kb` is a knowledge base and nothing else. This image is
# the other case: it runs the agent server, so it has to ask for the extra that
# provides it. Built without the brackets the container exits at start with
# `uvicorn: not found` -- invisible locally, because the gate installs `dev`,
# which pulls `app`. `app` depends on `gen`, so the model client comes with it.
RUN mkdir -p sextant/vector_db/ann sextant/mcp_server sextant/eval \
    && find sextant -type d -exec touch {}/__init__.py \; \
    && pip install --no-cache-dir -e '.[app]'

COPY sextant/ sextant/

# Bake the models into the image. Without this the first query after
# `docker compose up` silently downloads ~180 MB and appears to hang.
# Baked as `app`, not root: huggingface_hub takes a lock file in the cache
# when it loads a model, and a root-owned cache makes that write fail for
# the runtime user. Building the cache as the user that reads it is simpler
# than chowning it afterwards and proves the same thing.
# HF_HUB_OFFLINE stops the runtime from phoning home to check for newer
# weights on every start -- the image is the pin.
ENV HF_HOME=/opt/models HF_HUB_OFFLINE=1
RUN mkdir -p /opt/models && chown app:app /opt/models
USER app
RUN HF_HUB_OFFLINE=0 python -c "\
from sextant.vector_db.onnx_models import OnnxEmbedder, OnnxReranker; \
OnnxEmbedder('all-MiniLM-L6-v2'); \
OnnxReranker('cross-encoder/ms-marco-MiniLM-L-6-v2')"
USER root

# Written to a volume so ingested documents survive `docker compose down`.
# In production this path is a bind mount and the host's ownership wins; the
# chown here only covers the dev compose file's named volume.
ENV SEXTANT_CHROMA_DIR=/data/chroma
ENV SEXTANT_LOG_FORMAT=json
RUN mkdir -p /data/chroma && chown app:app /data/chroma

USER app
EXPOSE 8000
CMD ["uvicorn", "sextant.mcp_server.main:app", "--host", "0.0.0.0", "--port", "8000"]
