
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
