# --- Stage 1: test ---
# Runs pytest with coverage. Failing tests abort the build before anything is pushed.
# coverage/coverage.xml is copied into the production image so Jenkins can docker cp
# it out and forward it to SonarQube.
FROM public.ecr.aws/docker/library/python:3.13-slim AS test

RUN apt-get update && apt-get upgrade -y && apt-get clean && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
	PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY tests ./tests

RUN pip install --no-cache-dir -e ".[test]" && mkdir -p coverage && pytest


# --- Stage 2: production ---
FROM public.ecr.aws/docker/library/python:3.13-slim

# Security: Update system packages to patch known vulnerabilities
# Note: Some security patches for system libraries (like OpenSSL) are currently 
# unavailable in the official Debian 13 (Trixie) repositories. 
# These will be fixed automatically once the Debian Security Team and 
# Docker Hub release updated versions of the 'python:3.13-slim' image.
# Troubleshooting support: include vi and psql for ad-hoc pod exec debugging.
RUN apt-get update && apt-get upgrade -y && \
	apt-get install -y --no-install-recommends vim-tiny postgresql-client && \
	apt-get clean && rm -rf /var/lib/apt/lists/*
	

# Python runtime flags
ENV PYTHONDONTWRITEBYTECODE=1 \
	PYTHONUNBUFFERED=1

WORKDIR /app

# Package files
COPY pyproject.toml README.md ./
COPY src ./src

# Package install
# Security: Remove setuid and setgid permissions from all executables
# This prevents privilege escalation attacks (CIS Docker 4.8)
# Removes system utilities like passwd, su, chmod that are rarely needed in containers
# Focus on real filesystems (/usr/bin, /bin, /sbin, /usr/sbin) to avoid virtual fs errors
RUN pip install --no-cache-dir . && \
    find /usr/bin /bin /usr/sbin /sbin -perm /4000 -type f -delete 2>/dev/null || true

# Carry the coverage report forward so Jenkins can extract it with docker cp.
COPY --from=test /app/coverage ./coverage

# Security: Create non-root user to run the application
# UID 1000 is standard for application users (UID 0 is root)
# -m flag creates home directory with proper shell configuration
RUN useradd -m -u 1000 appuser

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

