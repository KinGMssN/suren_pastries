# E-commerce Website Audit Report

## 1. Summary

**Verdict: Not ready.** The customer sign-in and checkout path cannot complete as implemented, online payment is not integrated, and the delivery API exposes customer/order data while allowing unauthenticated order changes.

| Severity | Findings |
|---|---:|
| Critical | 1 |
| High | 6 |
| Medium | 12 |
| Low | 1 |
| **Total** | **20** |

Top five urgent issues:
1. The unauthenticated delivery API discloses active orders and lets callers assign or mark orders delivered (F-01).
2. Checkout trusts client-submitted prices and quantities (F-03).
3. “Pay online” creates an order without a payment-provider transaction or verification (F-04).
4. CSRF protection is disabled for admin API actions that can be triggered by simple POST requests (F-05).
5. Customer OTP login/signup endpoints are missing, so normal customers cannot establish the session required for account and checkout APIs (F-02).

## 2. Project overview

### Stack and structure

- **Backend:** Python 3.12; Flask 3.0.3; Flask-SQLAlchemy 3.1.1 / SQLAlchemy; Flask-Login; Flask-WTF; Flask-Limiter; Flask-CORS.
- **Database:** PostgreSQL, using psycopg 3.2.10. Docker Compose provides a local PostgreSQL 16 service.
- **Frontend:** Flask/Jinja server-rendered HTML with vanilla JavaScript and CSS; no frontend package manifest or frontend package manager.
- **Deployment:** Gunicorn 22.0.0 via `Procfile`; `runtime.txt` specifies Python 3.12.7. The local virtual environment is Python 3.12.12.
- **Python dependencies:** pinned in `requirements.txt`; no dependency lockfile is present. `README.md` is effectively empty, so setup and environment configuration are undocumented.
- **Folder map:** `app/` contains app initialization, authentication, permissions, models, blueprints, templates, CSS, and JavaScript; `scripts/seed.py` seeds a database; root files contain configuration, WSGI/deployment, dependency, and Docker Compose settings. No test directory is tracked.

### Routes and entry points

- **WSGI entry:** `wsgi.py` creates the Flask app; `Procfile` launches `gunicorn wsgi:app`.
- **HTML pages:** `/`, `/home`, `/menu`, `/about`, `/privacy`, `/refund-policy`, `/terms`, `/cookies`, `/cart`, `/login`, `/signup`, `/account`, `/delivery`, `/track/<order_number>`, `/delivery/order/<order_id>`, `/admin/login`, `/admin/logout`, `/admin/logout-everywhere`, and `/admin/`.
- **Other app routes:** `/.well-known/security.txt`; `/api/csp-report`.
- **API:** admin login/logout/reset/me; customer account deletion, addresses, and orders; public menu, coupon application, checkout, order tracking, delivery people/orders/detail/assignment/delivery; admin stats, deleted-records, orders/status, menu CRUD/toggles, coupons, content, team, and delivery-person management.
- **Route gaps:** the frontend calls `/api/customer/request-otp`, `/api/customer/verify-otp`, and `/api/customer/logout`, but the API blueprint does not define them. The About page calls `/api/team`, while the API only defines the admin team endpoints.

### Data models

`AdminUser`, `Category`, `MenuItem`, `TeamMember`, `Coupon`, `Customer`, `AuditLog`, `DeletedRecord`, `CustomerAddress`, `DeliveryPerson`, `Order`, `OrderItem`, and `SiteContent`.

Orders use `pending`, `preparing`, `ready`, and `delivered` statuses, and `whatsapp`, `online`, and `cod` channels. `MenuItem` has a boolean `in_stock` flag, not a quantity/reservation model.

### Environment/configuration

Configuration reads `SECRET_KEY`, `DATABASE_URL`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `SUBADMIN_USERNAME`, `SUBADMIN_PASSWORD`, `FRONTEND_ORIGIN`, `RENDER`, `CUSTOMER_OTP_DEBUG`, `ADMIN_RESET_KEY`, and `ADMIN_TOTP_SECRET`. `CUSTOMER_OTP_TTL_SECONDS`, delivery/tax defaults, idle timeout, and login-failure threshold are code defaults. No secret values are reproduced in this report.

### Feature map

- Present in source: menu/category listing and text search, local-storage cart, coupon calculation, COD/WhatsApp/online checkout buttons, order tracking, account/address/order-history UI, admin menu/order/coupon/content/team/delivery-roster screens, and a delivery portal.
- Missing or incomplete: customer authentication/session issuance; real online payment; WhatsApp handoff; reliable stock counts/decrement; product detail/variant pages; order cancellation/refund/retry; customer/order notifications; public team API; search filters/sorting/pagination; and a complete SEO metadata/sitemap setup. See Section 5.

## 3. Automated check results

| Check | Result |
|---|---|
| Python syntax | **Passed:** AST-parsed 13 project Python files without writing bytecode; no syntax errors. |
| JavaScript syntax | **Passed:** `node --check` passed for all 12 JavaScript files. |
| Dependency consistency | **Passed:** virtual-environment `pip check` reported no broken requirements. |
| Install check | **Passed (dry run):** all 11 pinned requirements were already satisfied; no packages were installed. |
| Tests | **Not run:** no test files are tracked and `pytest` is not installed in the project virtual environment. |
| Build | **Not applicable / not configured:** no build command or frontend package manifest exists. |
| Lint/type check | **Not run:** no configured lint/type-check command; `ruff` and `mypy` are not installed. |
| Known dependency vulnerabilities | **Not checked:** `pip-audit` is not installed. `npm audit` does not apply because there is no `package.json`. |
| Runtime/browser/DB verification | **Skipped:** app initialization executes database DDL/commits (`app/__init__.py`), and the seed script writes data. Starting the app or seeding would violate the read-only constraint. No live database, third-party payment/SMS services, or browser session was exercised. |

Suppressed/fallback errors noted in source: database schema/audit-log `SQLAlchemyError` handlers in `app/__init__.py`; broad fallback in `app/__init__.py`; image validation catch in `app/blueprints/api.py`; invalid coupon date silently ignored in `app/blueprints/api.py`; empty catches in `app/static/js/details.js` and `app/static/js/floating-widgets.js`. These can conceal operational failures; see F-16 and the route-specific findings.

## 4. Findings

Sorted by severity. “Confirmed” means the behavior is directly established by source; findings with runtime-dependent impact are marked “Suspected.”

| ID | Severity (Critical / High / Medium / Low) | Category | File:Line | Description | Impact | Suggested fix | Confirmed/Suspected |
|---|---|---|---|---|---|---|---|
| F-01 | Critical | Security / Access control | `app/blueprints/api.py:846-899` | Delivery people/order listing, order detail, assignment, and delivery-status endpoints have no authentication or authorization. The list returns all undelivered orders; any caller can assign an order or mark it delivered and set COD collection state. | Exposes customer names, phone numbers, addresses, items, and totals; enables order tampering and fraudulent “delivered/paid” status changes. | Require authenticated delivery accounts; authorize each order against the assigned delivery person; validate transitions and COD collection server-side; limit returned data. | Confirmed |
| F-02 | High | Breaking / Authentication | `app/static/js/customer.js:49,78,97,118,136`; `app/blueprints/api.py:165-255` | Customer UI calls OTP request, OTP verification, and logout endpoints that are not implemented. The existing account/address/order endpoints rely on `session["customer_id"]`, but no customer-auth route sets it. | Customers cannot sign up/log in through the site; account data and checkout cannot work through the normal UI. | Implement rate-limited OTP send/verify/logout routes, secure session issuance and expiry, and server-side customer identity checks; otherwise remove the unsupported UI. | Confirmed |
| F-03 | High | Checkout / Price integrity | `app/blueprints/api.py:341,379-383` | Checkout calculates subtotal from client-provided `price` and `qty`, then stores client-provided item names/prices/quantities without fetching current menu items or validating positive bounds/stock. | A caller with a customer session can tamper with item prices or quantities, create zero/negative/incorrect totals, and order unavailable items. | Accept only item IDs and quantities; load current available/in-stock items and prices from the database, validate quantity bounds, and recompute all amounts server-side. | Confirmed |
| F-04 | High | Payments | `app/static/js/cart.js:111-112,156-177`; `app/blueprints/api.py:318-359`; `app/models.py:214` | “Pay online” sends `channel: online` to the same order-creation endpoint as other channels. There is no payment-provider initiation, payment status, signature-verified callback/webhook, or verified transaction gate before the order is created. | Orders can be recorded as online without payment; the delivery UI treats non-COD orders as already paid. | Integrate a payment provider; create orders in an unpaid/pending-payment state; verify signed provider callbacks and reconcile failures/cancellations before marking paid or releasing fulfillment. | Confirmed |
| F-05 | High | Security / CSRF | `app/__init__.py:51-69`; `app/blueprints/api.py:603-629`; `config.py:40` | The entire API blueprint is CSRF-exempt. Authenticated menu toggle endpoints mutate state on POST without requiring JSON or a CSRF token. Production session cookies use `SameSite=None`. | A cross-site form can trigger menu/stock/special toggles while an administrator is signed in; CORS does not prevent a browser from submitting a simple form request. | Keep CSRF enabled for cookie-authenticated mutations; use per-request tokens or a robust origin check, and avoid cross-site cookies unless necessary. | Confirmed |
| F-06 | High | Security / Customer privacy | `app/blueprints/api.py:399-405`; `app/models.py:251-272` | Public order tracking returns `Order.to_dict()` including customer phone and full delivery address. Order numbers contain only three random bytes, and the tracking endpoint has no rate limit. | Anyone who obtains or guesses an order number can retrieve personal data; the short identifier makes enumeration more practical. | Return only tracking-safe fields; use high-entropy unguessable tracking tokens and rate-limit lookup attempts; require an authenticated customer for PII. | Confirmed |
| F-07 | High | Deployment / Debug security | `wsgi.py:6`; `Procfile:1` | Running `python wsgi.py` starts Flask’s debug server bound to all interfaces. The Procfile uses Gunicorn, but the debug path remains executable and the seed script advertises direct `python wsgi.py` startup. | If used on a reachable production host, the Werkzeug debugger can expose a dangerous interactive console. | Disable debug mode in the WSGI entry point; keep the debug server restricted to local development and use the production WSGI server for deployment. | Suspected (impact depends on how it is launched) |
| F-08 | Medium | Security / XSS | `app/blueprints/api.py:517-553`; `app/static/js/menu.js:71-81` | Admin-editable menu fields are returned as JSON and interpolated into `innerHTML` without escaping (including name, description, tag, emoji, image alt text, and category text). | A malicious or compromised menu administrator can persist markup/script payloads that execute for public menu visitors. | Render text with DOM `textContent`/safe templates; escape HTML contexts and restrict image sources/types; validate inputs as defense in depth. | Confirmed |
| F-09 | Medium | Deployment / Sessions | `config.py:10` | If `SECRET_KEY` is unset, each app process generates a fresh random key. | Sessions and CSRF tokens become invalid after restart; multiple workers can disagree on cookie signatures and cause intermittent logouts/auth failures. | Require a stable, strong `SECRET_KEY` in deployed environments and fail startup if it is missing. | Confirmed |
| F-10 | Medium | Frontend / CSP | `app/__init__.py:168-172`; `app/templates/cart.html:29,34`; `app/templates/admin/dashboard.html:212,265` | The CSP sets `style-src-attr 'none'` while templates and JavaScript use inline style attributes for visibility and layout. | Browsers enforcing this policy ignore those inline styles; hidden elements and intended layout/state changes may render incorrectly. | Move styles to classes in stylesheet files or permit only a safe, deliberate style strategy; verify the affected screens in a browser with CSP enabled. | Confirmed (policy conflict); visual impact not browser-tested |
| F-11 | Medium | Breaking / Content | `app/static/js/details.js:6-12`; `app/blueprints/api.py:727-755` | The About page fetches `/api/team`, but the only team API route is `/api/admin/team`. The failed fetch is swallowed. | Public team/chef content never loads and the empty failure is invisible to users. | Add a public, read-only team endpoint or change the frontend to use an existing public data source; display a visible fallback/error state. | Confirmed |
| F-12 | Medium | Inventory | `app/models.py:59-63`; `app/blueprints/api.py:341-386` | Inventory is only a boolean `in_stock` flag; checkout does not reserve or decrement stock. | Multiple concurrent orders can exceed available stock, and there is no quantity-based inventory audit. | Model quantity/reservations and decrement stock atomically within the order transaction; reject orders that exceed available stock. | Confirmed |
| F-13 | Medium | Checkout / Money | `app/blueprints/api.py:343`; `app/static/js/cart.js:52` | Backend tax uses Python `round()` (ties-to-even), while the cart preview uses JavaScript `Math.round()` (half-up for positive values). For example, a subtotal of 10 produces 0 backend tax and 1 in the browser at a 5% rate. | Checkout total can differ from the displayed order summary by one rupee at half-rupee tax values. | Use one explicit currency-rounding rule on the server and mirror it in the UI; treat the server result as authoritative. | Confirmed |
| F-14 | Medium | Data integrity | `app/blueprints/api.py:376-386` | The checkout loop commits once per item rather than committing the order and all items atomically. | If a later item insert fails, an order and earlier items may remain committed even though checkout returns an error; retries can create duplicate orders. | Add order and all line items in one transaction and commit once; roll back the entire order on any failure. | Confirmed |
| F-15 | Medium | Privacy / Data retention | `app/blueprints/api.py:40-50,166-185`; `app/models.py:166-175` | Customer account deletion archives the customer and every address, including identifying data, in `DeletedRecord`; no retention or purge path is present. | “Delete my account and saved addresses” does not remove that personal data from the application database. | Define and disclose a retention policy; redact or delete archived personal data when deletion is requested, unless a documented legal retention requirement applies. | Confirmed |
| F-16 | Medium | Reliability / Database migrations | `app/__init__.py:23-49,111` | App creation executes `ALTER TABLE` statements and commits on startup, catches database errors, and continues. `db.create_all()` is also run during app creation. | Startup mutates production schema, and failed schema changes are silent; the app can appear up while later queries fail against missing columns. | Use explicit, versioned migrations run as a deployment step; log/fail startup on migration errors and do not silently continue. | Confirmed |
| F-17 | Medium | Deployment / Database security | `docker-compose.yml:6-10` | The Compose file contains fixed development database credentials and publishes PostgreSQL on host port 5432 without a loopback-only bind. Values are intentionally omitted here. | Reusing this configuration on a shared or exposed host can make the database reachable with predictable credentials. | Keep Compose credentials local-only, load credentials from untracked environment configuration, and bind the local database port to loopback unless remote access is explicitly required. | Confirmed |
| F-18 | Medium | Security / Redirect handling | `app/blueprints/admin.py:39-40` | After successful admin login, the unvalidated `next` query parameter is passed directly to `redirect()`. | Attackers can use the login URL as an open redirect to send users to an external phishing site after authentication. | Accept only safe same-origin relative URLs or use an allowlist of internal endpoints. | Confirmed |
| F-19 | Medium | Checkout / WhatsApp | `app/static/js/cart.js:111,156-177`; `app/blueprints/api.py:318-359` | “Order via WhatsApp” creates an order through the API and redirects to the internal tracking page; it does not open WhatsApp, compose a message, or notify the business through WhatsApp. | The displayed order channel and promised action do not match what the customer experiences. | Implement a WhatsApp deep link/message handoff or relabel the action and provide an explicit, verified order-submission flow. | Confirmed |
| F-20 | Low | SEO | `app/templates/base.html:4-6` | The shared document head has charset, viewport, and title only; no meta description, canonical URL, sitemap, or robots file was found in the tracked project. | Search/social previews and crawl/indexing controls are incomplete. | Add page-appropriate metadata and canonical URLs, plus a sitemap and robots policy appropriate to the deployment. | Confirmed |

## 5. Missing or incomplete features

- **Customer auth:** OTP request/verification/logout API is missing; the customer session key is never established by a public route. Consequently address management, order history, account deletion, and checkout are not usable in the normal flow.
- **Payments:** no online payment provider, capture/verification, failure/cancel/retry handling, refunds, or webhook signature validation.
- **WhatsApp:** the button does not hand off to WhatsApp or send an order notification.
- **Inventory:** only a manual in-stock boolean exists; no stock quantity, reservation, or decrement.
- **Products:** no product-detail route/page, variants, or options. Menu provides category tabs and text search only; no sorting, advanced filters, or pagination.
- **Orders:** customer cancellation and refund flow is absent. Admin status changes exist, but there is no enforced transition model.
- **Notifications:** no email/SMS/order confirmation or new-order notification integration is present.
- **Content:** public team endpoint is missing, so the About page team section is blank.
- **SEO/setup:** no sitemap/robots/canonical metadata; `README.md` provides no usable setup or environment-variable instructions.
- **Testing/operations:** no tracked automated tests, migration framework, or configured lint/type-check pipeline.

## 6. Flows verified working

No e-commerce flow was verified end-to-end at runtime because doing so would require starting an app whose factory runs database DDL/commits, and no live DB/provider/browser was exercised.

Source-level checks only:
- The public menu frontend fetches `/api/menu`, and that route returns categories containing menu item dictionaries in the shape the menu renderer consumes.
- Main page links correspond to registered server-rendered routes.
- Admin API routes generally use login and role decorators; this does not address the separate CSRF and input-validation findings above.

These are source-level alignment checks, not a statement that the flows work in a deployed environment.

## 7. Not checked / limitations

- No application startup, database connection, seed run, migration, or database write was performed.
- No live browser, mobile/responsive, accessibility, console, network, or screen-reader testing.
- No payment provider, SMS/OTP delivery, email, or third-party integration credentials/services were available or exercised.
- No database contents were inspected; production schema compatibility, existing records, indexes, query plans, concurrency behavior, and backups remain unverified.
- `pip-audit` was unavailable, so dependency CVEs were not assessed.
- No runtime attack reproduction was performed; security findings are based on direct source tracing. F-07’s impact depends on launching the debug entry point.

## Final check

Only this report was created; no existing project file was modified. Every finding has a repository-relative file path and line reference. No secret value is included.
