# Suren Pastries — Flask + PostgreSQL

Your six static HTML pages (loader, landing, menu, about, cart, admin) rebuilt
as a real Flask application: clean routes, Jinja templates, separated
CSS/JS, Bootstrap 5 for extra responsiveness, a PostgreSQL database, and a
working admin panel where you can edit the menu, offers, orders and site
text without touching code.

## What changed from the static mockups

- **One Flask app**, not six standalone HTML files. Shared layout lives in
  `app/templates/base.html`; each page extends it.
- **CSS/JS split out** of `<style>`/`<script>` tags into
  `app/static/css/*.css` and `app/static/js/*.js`.
- **Bootstrap 5** is loaded via CDN in `base.html` for grid/utility classes,
  layered on top of your original design system (CSS variables, fonts,
  animations) so the boutique look is unchanged.
- **The menu is now a database**, not a hardcoded JS object. `menu.html`
  fetches `/api/menu`, which reads from PostgreSQL.
- **Checkout creates a real order** in the database (`orders` /
  `order_items` tables) instead of just showing a success popup.
- **The admin panel is real**: it requires a hashed username/password login
  (Flask-Login), and every action (add/edit/delete menu items, create
  offers, update order status, edit site text) writes to PostgreSQL through
  a small JSON API under `/api/admin/*`.

## Project layout

```
suren_pastries/
├── app/                        # Flask backend (deploy to Render)
│   ├── __init__.py            # app factory + CORS setup
│   ├── extensions.py          # db, login_manager
│   ├── models.py              # AdminUser, Category, MenuItem, Coupon, Order, OrderItem, SiteContent
│   ├── blueprints/
│   │   ├── main.py            # server-rendered pages (local dev only): /, /home, /menu, /about, /cart
│   │   ├── api.py             # /api/menu, /api/checkout, /api/coupon/apply, /api/content,
│   │   │                      # /api/specials, /api/auth/*, /api/admin/*
│   │   └── admin.py           # server-rendered admin login (local dev only)
│   ├── templates/              # used only in local server-rendered mode
│   └── static/                 # used only in local server-rendered mode
├── frontend/                    # Static site (deploy to GitHub Pages)
│   ├── index.html, landing.html, menu.html, about.html, cart.html
│   ├── admin/login.html, admin/dashboard.html, admin/js/
│   ├── css/                    # same stylesheets as app/static/css
│   └── js/config.js            # ← set your Render backend URL here
├── scripts/seed.py            # creates tables + admin user + seed data
├── config.py
├── wsgi.py                    # entry point
├── Procfile                   # tells Render how to start the app
├── requirements.txt
├── docker-compose.yml         # optional local Postgres
└── .env.example
```

## Local development (server-rendered mode)

The original all-in-one Flask app (Jinja templates, no GitHub Pages split)
is the easiest way to develop and test locally — use this while you're
making changes, then deploy the split version (below) when you're ready to
publish.

### 1. Set up PostgreSQL

Easiest path — Docker:

```bash
docker compose up -d
```

This starts Postgres on `localhost:5432` with database `suren_pastries`,
user `suren_user`, password `suren_pass` (matches `.env.example`).

No Docker? Install PostgreSQL locally and create a database + user that
match whatever you put in `DATABASE_URL`:

```sql
CREATE DATABASE suren_pastries;
CREATE USER suren_user WITH PASSWORD 'suren_pass';
GRANT ALL PRIVILEGES ON DATABASE suren_pastries TO suren_user;
```

### 2. Configure the app

```bash
cp .env.example .env
```

Edit `.env`:
- `SECRET_KEY` — any long random string
- `DATABASE_URL` — your Postgres connection string
- `ADMIN_USERNAME` / `ADMIN_PASSWORD` — the login the seed script will create

### 3. Install dependencies & seed the database

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
python scripts/seed.py
```

The seed script creates all tables, your admin login, the original 30-dish
menu, two starter coupons (`SUREN20`, `FLAT50`), and default site text. It's
safe to re-run — it won't duplicate data, and re-running it does reset the
admin password from `.env` if you ever forget it.

### 4. Run it

```bash
flask --app wsgi run --debug
# or: python wsgi.py
```

Visit `http://localhost:5000`. Admin panel: `http://localhost:5000/admin/login`.

## Deploying: GitHub Pages (frontend) + Render (backend)

GitHub Pages only serves static files — it can't run Flask or connect to
PostgreSQL. So this project is split into two pieces that talk to each
other over the network:

- **`app/` + `wsgi.py`** → the Flask API + Postgres backend → deploy to **Render**
- **`frontend/`** → plain HTML/CSS/JS that calls that API → deploy to **GitHub Pages**

### Step 1 — Push this project to a GitHub repo

```bash
git init
git add .
git commit -m "Suren Pastries — Flask backend + static frontend"
git branch -M main
git remote add origin https://github.com/<your-username>/<your-repo>.git
git push -u origin main
```

### Step 2 — Deploy the backend to Render

1. Go to [render.com](https://render.com) → sign up/log in with GitHub.
2. **New → PostgreSQL.** Name it `suren-pastries-db`, choose the free plan,
   create it. Once it's up, copy the **Internal Database URL** shown on its
   page (starts with `postgresql://`).
3. **New → Web Service** → connect the GitHub repo you just pushed.
   - **Root directory:** leave blank (repo root)
   - **Runtime:** Python 3
   - **Build command:** `pip install -r requirements.txt`
   - **Start command:** `gunicorn wsgi:app` (Render also auto-detects this
     from the `Procfile`)
4. Under **Environment**, add these variables:
   | Key | Value |
   |---|---|
   | `DATABASE_URL` | the Internal Database URL from step 2 |
   | `SECRET_KEY` | any long random string |
   | `ADMIN_USERNAME` | your choice |
   | `ADMIN_PASSWORD` | your choice |
   | `FRONTEND_ORIGIN` | `https://<your-username>.github.io` (no trailing slash — you'll confirm this in step 4) |
5. Click **Create Web Service**. Render will build and deploy — first
   deploy takes a few minutes. Note the URL it gives you, e.g.
   `https://suren-pastries.onrender.com`.
6. Seed the database once: in the Render dashboard, open your web service →
   **Shell** tab, and run:
   ```bash
   python scripts/seed.py
   ```
   (Alternatively add this as a Render **Job** or run it from your own
   machine with `DATABASE_URL` pointed at the database's **External**
   connection string instead of the internal one.)
7. Confirm it's alive: visit `https://suren-pastries.onrender.com/api/menu`
   in your browser — you should see JSON.

> Free Render web services spin down after periods of inactivity and take
> ~30–50 seconds to wake up on the next request. That's normal on the free
> tier, not a bug.

### Step 3 — Point the frontend at your backend

Edit **one file**: `frontend/js/config.js`

```js
window.API_BASE = "https://suren-pastries.onrender.com";
```

(use the exact URL Render gave you, no trailing slash)

### Step 4 — Deploy the frontend to GitHub Pages

Simplest option — serve the `frontend/` folder directly from your repo:

1. Commit the `config.js` change and push:
   ```bash
   git add frontend/js/config.js
   git commit -m "Point frontend at Render backend"
   git push
   ```
2. On GitHub: repo → **Settings → Pages**.
3. Under **Build and deployment → Source**, choose **Deploy from a branch**.
4. **Branch:** `main`, **Folder:** you need `frontend/` as the site root.
   GitHub Pages only offers `/ (root)` or `/docs` in that dropdown, so
   either:
   - **Option A (recommended):** rename the `frontend/` folder to `docs/`
     (`git mv frontend docs`, update nothing else — it's just a folder
     name), then select **Folder: /docs**, or
   - **Option B:** create a separate repo containing only the contents of
     `frontend/` at its root, and select **Folder: / (root)**.
5. Save. GitHub gives you a URL like
   `https://<your-username>.github.io/<your-repo>/` (Option A) or
   `https://<your-username>.github.io/` (Option B, if it's your
   `<username>.github.io` repo).
6. **Go back to Render** and make sure `FRONTEND_ORIGIN` exactly matches
   that URL with **no trailing slash** (e.g.
   `https://your-username.github.io`, not
   `https://your-username.github.io/your-repo/`) — CORS checks the origin,
   which is just scheme+host, not the path. Redeploy the Render service
   after changing this env var so it picks up the new value.

### Step 5 — Test it live

Visit your GitHub Pages URL:
- `index.html` → loader → `landing.html` should load and show specials
  fetched from Render
- `menu.html` → dishes fetched from `/api/menu`
- Add items, go to `cart.html`, place an order via WhatsApp or online —
  this creates a real row in your Render Postgres database
- `admin/login.html` → sign in with the `ADMIN_USERNAME`/`ADMIN_PASSWORD`
  you set on Render → dashboard should show that order

If login succeeds but the dashboard immediately bounces you back to the
login page, it's almost always `FRONTEND_ORIGIN` not matching your Pages
URL exactly, or `config.js` pointing at the wrong Render URL — check both,
then redeploy Render after fixing `FRONTEND_ORIGIN`.

### Why this doesn't work over two `localhost` ports

If you try to reproduce this split locally (e.g. Flask on :5000, a static
server on :8080), the admin login cookie won't persist between requests in
a real browser. That's because cross-site cookies require
`SameSite=None; Secure`, which **requires HTTPS** — `config.py` only turns
that on when it detects it's running on Render (`RENDER` env var). Locally,
just use the server-rendered pages (`python wsgi.py`, visit
`localhost:5000`) to test — the split frontend/backend setup is meant to be
tested on the real HTTPS deployments, not two local ports.

---

## Admin panel — what you can edit

- **Dashboard** — revenue, order counts, recent orders at a glance.
- **Orders** — every order placed through checkout, filterable by status,
  with a dropdown to move each one through pending → preparing → ready →
  delivered.
- **Menu** — add, edit, hide/show, or delete any dish. Categories are
  created on the fly — type a new category name and it appears as a new
  tab on the public menu page.
- **Offers** — create/disable/delete promo codes (percent or flat ₹ off),
  used by the coupon box in the cart.
- **Content** — the phone/email/address shown on the About page, and the
  hero headline/stats on the landing page, all editable without code.

## Notes

- Prices are stored as whole rupees (integers), matching the original
  design — no paise/decimals anywhere in the UI.
- The cart itself still lives in the browser's `localStorage` (no login
  required to shop), exactly like the original static prototype. It's only
  turned into a permanent `Order` row in Postgres at checkout.
- `emoji` fields are simple text (e.g. `🍛`) rather than uploaded images,
  matching the original design's placeholder-art approach. Swapping these
  for real product photos would mean adding an `image_url` column and a
  file upload — happy to add that if you want real photography instead.
