# Audit Fix Report

## Summary

All 20 findings in `AUDIT_REPORT.md` have a corresponding implementation or
fail-closed mitigation committed on `fix/audit-findings`. The fixes address
security, checkout integrity, inventory, privacy, migrations, deployment
configuration, and SEO. Provider-dependent features remain unavailable until
their integrations are configured.

The full test suite passes: **39 passed, 212 warnings**. No production
dependency or lockfile was changed; the development requirements support the
test suite.

## Findings addressed

| Finding | Status | Commit |
|---|---|---|
| F-01 | Delivery operations require appropriate authorization and are limited to assigned orders. | `9e38e3f` |
| F-02 | Customer OTP/session endpoints and expiry/attempt handling are implemented. Production signup/login fails closed until an SMS provider is configured. | `a498dc8` |
| F-03 | Checkout recomputes item prices and totals on the server. | `f8f79a6` |
| F-04 | Online payments are rejected until a payment provider and verified payment flow are integrated. | `7fb62e4` |
| F-05 | API mutations validate request origin. | `efbda47` |
| F-06 | Public tracking uses privacy protections, higher-entropy identifiers, and rate limiting. | `5da2b0d` |
| F-07 | The exposed debug server is disabled. | `7da94f9` |
| F-08 | Public menu content is escaped before rendering. | `c1bf027` |
| F-09 | Production startup requires a configured secret key. | `5e2c3eb` |
| F-10 | CSP allows required inline style attributes while keeping script execution nonce-based. | `b75d43e` |
| F-11 | Public team data is served and the About page has explicit states. | `eb6dee9` |
| F-12 | Finite inventory is validated and decremented atomically; legacy `NULL` stock remains unlimited. | `ef675b3` |
| F-13 | Checkout and browser totals use consistent currency rounding. | `22e792a` |
| F-14 | Order creation and its items are committed atomically with idempotency protection. | `fdf0b59` |
| F-15 | Account deletion removes saved addresses, retains only customer name/mobile in the purgeable archive, and anonymizes order contact and delivery details. Super admins can manually purge archived records. | `72d974d` |
| F-16 | Schema changes run through explicit versioned migrations instead of app startup. | `ce3c3bf` |
| F-17 | Compose database credentials come from environment configuration and the host port binds to loopback. | `089b0d9` |
| F-18 | Admin post-login redirects are restricted to safe relative paths. | `71d6890` |
| F-19 | The misleading WhatsApp checkout is disabled; COD remains available. | `426a396` |
| F-20 | SEO descriptions, canonicals, robots rules, and a sitemap are provided when the public site URL is configured. | `8b4758e` |

## Verification

- `python -m pytest -q`: **39 passed, 212 warnings**.
- `node --check app/static/js/admin.js`: passed.
- Python AST parsing of the changed API and retention test files: passed.
- `git diff --check`: passed.
- The migration runner was exercised against ephemeral SQLite during the migration fix.
- `pip check` passed during the earlier implementation phase; dependencies have not changed since.

The test warnings are primarily existing SQLAlchemy datetime/API deprecations
and Flask-Limiter's in-memory test storage warning.

## Deployment and outstanding integrations

- Before deployment, configure `DATABASE_URL` and run `flask --app wsgi db-upgrade`
  once as a deployment step. Back up the production database first.
- Configure `PUBLIC_SITE_URL` with the canonical site origin to enable absolute
  canonical URLs and the sitemap.
- Select and configure an SMS provider before enabling customer signup/login in
  production.
- Integrate a payment provider, including verified webhooks, before accepting
  online payments. Online payment remains intentionally rejected until then.
- WhatsApp ordering remains disabled until a real WhatsApp handoff/integration
  is implemented.
- Migration execution against the production PostgreSQL setup was not verified
  locally because the installed psycopg runtime could not load libpq.
- Live third-party integrations, production data, and browser-based responsive
  testing were not exercised.
