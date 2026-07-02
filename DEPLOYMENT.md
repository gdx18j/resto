# Production deployment

This Compose setup is intentionally strict: required production secrets have no
fallback values. If `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`,
`DB_NAME`, `DB_USER`, `DB_PASSWORD`, `EMAIL_BACKEND`, or `DEFAULT_FROM_EMAIL`
are missing or empty, `docker compose` must fail before services start. SMTP
email also fails at application startup when `EMAIL_HOST`, `EMAIL_PORT`, or
TLS/SSL are not configured for production.

## Environment

1. Copy `.env.example` to `.env`.
2. Fill every blank required value.
3. Generate a unique `DJANGO_SECRET_KEY`.
4. Set `DJANGO_DEBUG=False`.
5. Set `DJANGO_ALLOWED_HOSTS` to the real domain names plus the healthcheck host.
6. Set `DJANGO_CSRF_TRUSTED_ORIGINS` to the HTTPS origins, for example
   `https://restaurant.example.com`.
7. Configure a real email delivery backend. Email verification is mandatory,
   so production must not use console, dummy, locmem, or file-based backends.

PostgreSQL and Redis are available only on the internal Docker network. The web
container binds to `127.0.0.1:8000` by default. Put Nginx, a load balancer, or
another reverse proxy in front of it for public traffic.

## Rate Limiting

Production requires `REDIS_URL`; application rate-limit counters must be shared
across Gunicorn workers. Django limits POST requests for login, signup,
password reset, password reset confirmation, Google OAuth initiation, AI ask,
cart quote, and order creation.

The bundled Nginx TLS profile also applies per-IP `limit_req` rules to the same
critical endpoints before the request reaches Django. If another trusted load
balancer sits in front of Nginx, configure Nginx `real_ip_header` and
`set_real_ip_from` for that network so proxy limits use the real client IP.

## Email

Production requires a delivery-capable email backend. For SMTP:

```env
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.example.com
EMAIL_PORT=587
EMAIL_HOST_USER=transactional-user
EMAIL_HOST_PASSWORD=transactional-password
EMAIL_USE_TLS=True
EMAIL_USE_SSL=False
DEFAULT_FROM_EMAIL="Caesar & Company <no-reply@example.com>"
SERVER_EMAIL=ops@example.com
EMAIL_SUBJECT_PREFIX="[Caesar & Company] "
```

Do not use `django.core.mail.backends.console.EmailBackend` in production:
verification and password-reset links would be written to container output and
could be collected by centralized logs.

## Start without TLS profile

Use this when TLS is terminated by an external load balancer:

```bash
docker compose up -d --build
```

## Start with bundled Nginx TLS profile

Place certificate files in `deploy/nginx/certs/`:

- `fullchain.pem`
- `privkey.pem`

Then run:

```bash
docker compose --profile tls up -d --build
```

The Nginx profile redirects HTTP to HTTPS and proxies to the internal `web`
service. Keep `DJANGO_SECURE_PROXY_SSL_HEADER=True`.

## Centralized logs

The base Compose file rotates local Docker JSON logs. To ship logs to a
GELF-compatible collector such as Graylog or Logstash, set `GELF_ADDRESS`, for
example `udp://logs.example.com:12201`, and run with the logging override:

```bash
docker compose -f docker-compose.yml -f deploy/docker-compose.logging.gelf.yml up -d
```

## Backup

Create a PostgreSQL custom-format dump:

```bash
sh ops/backup_postgres.sh
```

The default destination is `backups/resto_postgres_<UTC timestamp>.dump`. To
choose a path:

```bash
sh ops/backup_postgres.sh backups/pre-release.dump
```

## Restore

Restore is destructive for objects contained in the dump. Test it on a staging
database before production use:

```bash
sh ops/restore_postgres.sh backups/pre-release.dump
```

## Healthchecks

The application exposes `GET /healthz/`. Compose checks the web container
directly and the TLS profile checks Nginx over HTTPS.
