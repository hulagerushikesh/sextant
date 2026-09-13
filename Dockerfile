# The agent server, with the knowledge-base MCP server as its subprocess.
#
# Built on the full python image rather than -slim on purpose: chromadb and
# sentence-transformers pull in packages that want a compiler, and trading a
# larger base for a build that works first time is the right way round for
# something people run once to try the project.
FROM python:3.12

WORKDIR /app

# Dependency install is its own layer, so editing source does not re-resolve
# and re-download two gigabytes of torch.
COPY pyproject.toml README.md ./
# CPU-only torch FIRST. On linux/x86 the default torch wheel is the CUDA build
# and drags in ~3 GB of nvidia_* libraries that a CPU VM can never use -- it
# turns a 2 GB image into a 6 GB one and every rebuild re-downloads it. With
# a satisfying torch already present, `pip install -e .` leaves it alone.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
RUN mkdir -p mcp_server tools/vector_db eval \
    && touch mcp_server/__init__.py tools/__init__.py tools/vector_db/__init__.py eval/__init__.py \
    && pip install --no-cache-dir -e .

COPY mcp_server/ mcp_server/
COPY tools/ tools/
COPY eval/ eval/

# Bake the models into the image. Without this the first query after
# `docker compose up` silently downloads ~180 MB and appears to hang.
ENV HF_HOME=/opt/models
RUN python -c "\
from sentence_transformers import CrossEncoder, SentenceTransformer; \
SentenceTransformer('all-MiniLM-L6-v2'); \
CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')"

# Written to a volume so ingested documents survive `docker compose down`.
ENV AGENTICRAG_CHROMA_DIR=/data/chroma
ENV AGENTICRAG_LOG_FORMAT=json
RUN mkdir -p /data/chroma

EXPOSE 8000
CMD ["uvicorn", "mcp_server.main:app", "--host", "0.0.0.0", "--port", "8000"]
