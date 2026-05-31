FROM docker:cli AS dockercli

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=dockercli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=moby/buildkit:master /usr/bin/buildctl /usr/local/bin/buildctl

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN pip install --no-cache-dir --upgrade pip
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd -m -s /bin/bash deployhub \
    && chown -R deployhub:deployhub /app /opt/venv
USER deployhub

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
