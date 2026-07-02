# Production deployment

This Compose setup is intentionally strict: required production secrets have no
fallback values. If `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`,
`DB_NAME`, `DB_USER`, or `DB_PASSWORD` are missing or empty, `docker compose`
must fail before services start.

## Environment

1. Copy `.env.example` to `.env`.
2. Fill every blank required value.
3. Generate a unique `DJANGO_SECRET_KEY`.
4. Set `DJANGO_DEBUG=False`.
5. Set `DJANGO_ALLOWED_HOSTS` to the real domain names plus the healthcheck host.
6. Set `DJANGO_CSRF_TRUSTED_ORIGINS` to the HTTPS origins, for example
   `https://restaurant.example.com`.

PostgreSQL and Redis are available only on the internal Docker network. The web
container binds to `127.0.0.1:8000` by default. Put Nginx, a load balancer, or
another reverse proxy in front of it for public traffic.

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
