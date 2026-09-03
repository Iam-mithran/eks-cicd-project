# The image the pipeline builds once (Step 6), pushes to ECR (Step 7) and
# deploys to EKS (Step 8) — the SAME image in staging and production.
#
# Two stages: the builder compiles wheels, the runtime carries only what is
# needed to serve traffic. Compilers, headers and the pip cache never reach
# production. Smaller image, faster pod start, less to attack.

# ── Stage 1: build the dependencies ─────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# Copy the requirements file FIRST, on its own. Docker caches each layer and
# throws away everything after the first change — source changes on every
# commit, dependencies almost never do. Copy the source before this and you
# reinstall every dependency on every single build.
COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip \
    && pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

# ── Stage 2: the runtime image ──────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# Unbuffered stdout, or your logs sit in a buffer and `kubectl logs` shows
# nothing while you are trying to debug a live incident.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# Run as a non-root user. Containers are root unless you say otherwise, and
# root in the container is one escape away from root on the node. The
# Kubernetes Deployment enforces this a second time with runAsNonRoot — belt
# and braces, because this is the single cheapest hardening step there is.
RUN useradd --create-home --uid 10001 appuser

WORKDIR /app

COPY --from=builder /wheels /wheels
COPY requirements.txt .
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels

COPY app/ ./app/

USER appuser

EXPOSE 8000

# The pipeline overwrites RELEASE with the git SHA at deploy time so a running
# pod can tell you which commit it is.
ENV APP_NAME=taskapi \
    ENVIRONMENT=container \
    RELEASE=dev

# exec form (no shell), so uvicorn is PID 1 and receives SIGTERM directly.
# With the shell form, the shell swallows the signal, the pod ignores the
# graceful-shutdown window and Kubernetes SIGKILLs it 30s later — dropping
# in-flight requests on every single deploy.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
