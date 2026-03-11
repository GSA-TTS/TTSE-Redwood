FROM public.ecr.aws/docker/library/python:3.13-slim

# Python runtime flags
ENV PYTHONDONTWRITEBYTECODE=1 \
	PYTHONUNBUFFERED=1

WORKDIR /app

# Package files
COPY pyproject.toml README.md ./
COPY src ./src

# Package install
RUN pip install --no-cache-dir .

# Agent entrypoint
ENTRYPOINT ["python", "-m", "redwood_dataagent"]

