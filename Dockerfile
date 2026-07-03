FROM python:3.11-slim

ARG APP_UID=10001
ARG APP_GID=10001

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/home/resto

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        postgresql-client \
    && groupadd --gid "${APP_GID}" resto \
    && useradd \
        --uid "${APP_UID}" \
        --gid "${APP_GID}" \
        --create-home \
        --shell /usr/sbin/nologin \
        resto \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

COPY --chown=resto:resto . .
COPY --chown=root:root entrypoint.sh /usr/local/bin/resto-entrypoint

RUN sed -i 's/\r$//' /usr/local/bin/resto-entrypoint /app/ops/release.sh \
    && chmod 0755 /usr/local/bin/resto-entrypoint /app/ops/release.sh \
    && mkdir -p /app/staticfiles /app/mediafiles /home/resto \
    && chown resto:resto /app /app/staticfiles /app/mediafiles /home/resto

USER resto:resto

EXPOSE 8000

ENTRYPOINT ["/usr/local/bin/resto-entrypoint"]
CMD ["sh", "-c", "gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers ${GUNICORN_WORKERS:-3} --timeout ${GUNICORN_TIMEOUT:-60} --access-logfile - --error-logfile -"]
