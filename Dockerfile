# --- Stage 1: test ---
# Runs pytest with coverage. Failing tests abort the build before anything is pushed.
# coverage/coverage.xml is copied into the production image so Jenkins can docker cp
# it out and forward it to SonarQube.
FROM public.ecr.aws/docker/library/python:3.13-alpine AS test

RUN apk upgrade --no-cache

ENV PYTHONDONTWRITEBYTECODE=1 \
	PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY config ./config
COPY src ./src
COPY tests ./tests

RUN pip install --no-cache-dir -e ".[test]" && mkdir -p coverage && pytest


# --- Stage 2: production ---
FROM public.ecr.aws/docker/library/python:3.13-alpine

# Alpine uses musl libc and does not include perl in any image layer,
# eliminating the perl CVE surface that was present in the Debian-based slim image.
# Any residual CVEs are from the upstream Alpine base layer.
RUN apk upgrade --no-cache && \
	rm -f /etc/fstab && \
	rm -f /usr/sbin/crond /usr/bin/crontab
	

# Python runtime flags
ENV PYTHONDONTWRITEBYTECODE=1 \
	PYTHONUNBUFFERED=1

WORKDIR /app

# Package files
COPY pyproject.toml README.md ./
COPY config ./config
COPY src ./src

# Package install
# Strip setuid and setgid bits from all executables (CIS Docker 4.8).
# Prevents privilege escalation if a process is compromised inside the container.
RUN pip install --no-cache-dir . && \
    find /usr/bin /bin /usr/sbin /sbin /usr/lib -perm /6000 -type f -exec chmod a-s {} \; 2>/dev/null || true

# Carry the coverage report forward so Jenkins can extract it with docker cp.
COPY --from=test /app/coverage ./coverage

# Security: Create non-root user to run the application
# UID 1000 is standard for application users (UID 0 is root)
# -m flag creates home directory with proper shell configuration
RUN adduser -D -u 1000 appuser

# Switch to non-root user for enhanced security
USER appuser

# Health check to verify container is functioning
# Docker will periodically execute this command to determine container health
# Exit code 0 = healthy, non-zero = unhealthy
# Kubernetes uses this to decide whether to restart or remove the pod
# TODO: Replace with actual service health check (e.g., HTTP endpoint, queue check) once application is ready
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import sys; sys.exit(0)" || exit 1

# Agent entrypoint
ENTRYPOINT ["python", "-m", "redwood_dataagent"]

