
# Database schema

The application does not create or alter database tables during startup. Before
starting a new deployment or deploying a schema change, configure `DATABASE_URL`
and run the versioned migration command:

```text
flask --app wsgi db-upgrade
```

Run this command once as a deployment step, before starting the web workers.
It creates the base schema when needed, applies outstanding migrations, and
records completed versions in `schema_migrations`. Back up production data
before applying migrations.

For local development and tests, install the pinned development requirements:

```text
python -m pip install -r requirements-dev.txt
python -m pytest
```

## Local PostgreSQL

Copy `.env.example` to `.env`, set a unique local database username and strong
password, then start PostgreSQL with `docker compose up -d db`. The published
database port is bound to loopback only; `POSTGRES_PORT` can change its host
port. Configure `DATABASE_URL` to use the same local database credentials.
The `.env` file is ignored by Git and must not be committed.

Set `PUBLIC_SITE_URL` in the deployment environment to the canonical public
site origin (scheme and host only, with no trailing path). This enables absolute
canonical links, `robots.txt` sitemap discovery, and `/sitemap.xml`. The
sitemap is unavailable until this origin is configured.
