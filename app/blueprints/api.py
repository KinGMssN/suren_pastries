from datetime import datetime

from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user, login_required, login_user, logout_user

from app.extensions import db
from app.models import (
    AdminUser,
    Category,
    Coupon,
    MenuItem,
    Order,
    OrderItem,
    ORDER_CHANNELS,
    ORDER_STATUSES,
    SiteContent,
    TeamMember,
)

api_bp = Blueprint("api", __name__)


# ───────────────────────── helpers ─────────────────────────

def error(message, status=400):
    return jsonify({"ok": False, "error": message}), status


# ───────────────────────── one-time remote bootstrap ─────────────────────────
# Lets you seed the database by visiting a URL in the browser, for platforms
# (like Render's free tier) that don't give shell access. Protected by the
# SEED_KEY environment variable — set it on Render, visit this URL once,
# then remove the env var (or leave it, it's a no-op once already seeded).

@api_bp.route("/bootstrap")
def bootstrap():
    seed_key = current_app.config.get("SEED_KEY")
    if not seed_key:
        return error("SEED_KEY is not set on the server — add it in Render's Environment tab first.", 403)
    if request.args.get("key") != seed_key:
        return error("Wrong or missing ?key=... parameter.", 403)

    from sqlalchemy import text

    from app.models import AdminUser, Category, Coupon, MenuItem, SiteContent, TeamMember
    from scripts.seed import MENU_DATA, DEFAULT_CONTENT, TEAM_DATA

    db.create_all()  # creates any brand-new tables (e.g. team_members)
    log = []

    # Additive schema migration — safe to re-run, adds columns that were
    # introduced after the table already existed on this database.
    for stmt in [
        "ALTER TABLE menu_items ADD COLUMN IF NOT EXISTS in_stock BOOLEAN NOT NULL DEFAULT TRUE",
        "ALTER TABLE menu_items ADD COLUMN IF NOT EXISTS is_special BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE menu_items ADD COLUMN IF NOT EXISTS image_data TEXT",
    ]:
        db.session.execute(text(stmt))
    db.session.commit()
    log.append("Schema up to date (in_stock, is_special, image_data columns present).")

    username = current_app.config["ADMIN_USERNAME"]
    password = current_app.config["ADMIN_PASSWORD"]
    user = AdminUser.query.filter_by(username=username).first()
    if user is None:
        user = AdminUser(username=username)
        user.set_password(password)
        db.session.add(user)
        log.append(f"Created admin user '{username}'.")
    else:
        user.set_password(password)
        log.append(f"Admin user '{username}' already existed — password reset from env.")

    if MenuItem.query.count() == 0:
        for order, (cat_name, items) in enumerate(MENU_DATA.items()):
            category = Category(name=cat_name, sort_order=order)
            db.session.add(category)
            db.session.flush()
            for item in items:
                db.session.add(MenuItem(category_id=category.id, is_available=True, **item))
        log.append(f"Seeded {sum(len(v) for v in MENU_DATA.values())} menu items across {len(MENU_DATA)} categories.")
    else:
        log.append("Menu already has items — skipped menu seeding.")

    if Coupon.query.count() == 0:
        db.session.add(Coupon(code="SUREN20", description="20% off your order", discount_type="percent", value=20, active=True))
        db.session.add(Coupon(code="FLAT50", description="₹50 off your order", discount_type="flat", value=50, active=True))
        log.append("Seeded starter coupons SUREN20 and FLAT50.")
    else:
        log.append("Coupons already exist — skipped coupon seeding.")

    if TeamMember.query.count() == 0:
        for order, member in enumerate(TEAM_DATA):
            db.session.add(TeamMember(sort_order=order, **member))
        log.append(f"Seeded {len(TEAM_DATA)} team members.")
    else:
        log.append("Team members already exist — skipped team seeding.")

    for key, value in DEFAULT_CONTENT.items():
        if SiteContent.query.get(key) is None:
            db.session.add(SiteContent(key=key, value=value))
    log.append("Ensured default site content is present.")

    db.session.commit()
    return jsonify({"ok": True, "log": log})


# ───────────────────────── auth (JSON, for the static frontend) ─────────────────────────

@api_bp.route("/auth/login", methods=["POST"])
def auth_login():
    payload = request.get_json(silent=True) or {}
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""

    user = AdminUser.query.filter_by(username=username).first()
    if not user or not user.check_password(password):
        return error("Invalid username or password.", 401)

    login_user(user)
    return jsonify({"ok": True, "username": user.username})


@api_bp.route("/auth/logout", methods=["POST"])
@login_required
def auth_logout():
    logout_user()
    return jsonify({"ok": True})


@api_bp.route("/auth/me")
def auth_me():
    if current_user.is_authenticated:
        return jsonify({"ok": True, "authenticated": True, "username": current_user.username})
    return jsonify({"ok": True, "authenticated": False})


# ───────────────────────── public: site content + specials ─────────────────────────
# (read-only, no login — the old /api/admin/content GET required auth, which
# doesn't work for the static landing/about pages that need this on load)

@api_bp.route("/content")
def public_content():
    rows = SiteContent.query.all()
    return jsonify({r.key: r.value for r in rows})


@api_bp.route("/specials")
def public_specials():
    items = (
        MenuItem.query.filter(MenuItem.is_special.is_(True), MenuItem.is_available.is_(True))
        .order_by(MenuItem.id)
        .limit(8)
        .all()
    )
    return jsonify([i.to_dict() for i in items])


@api_bp.route("/team")
def public_team():
    members = TeamMember.query.order_by(TeamMember.sort_order, TeamMember.id).all()
    return jsonify([m.to_dict() for m in members])


# ───────────────────────── public: menu ─────────────────────────

@api_bp.route("/menu")
def get_menu():
    """Grouped-by-category menu, in the same shape the original static
    JS `menu` object used, so the front-end rendering logic barely changes."""
    categories = Category.query.order_by(Category.sort_order, Category.name).all()
    data = {}
    for cat in categories:
        items = (
            MenuItem.query.filter_by(category_id=cat.id, is_available=True)
            .order_by(MenuItem.id)
            .all()
        )
        data[cat.name] = [i.to_dict() for i in items]
    return jsonify(data)


# ───────────────────────── public: coupon ─────────────────────────

@api_bp.route("/coupon/apply", methods=["POST"])
def apply_coupon():
    payload = request.get_json(silent=True) or {}
    code = (payload.get("code") or "").strip().upper()
    subtotal = int(payload.get("subtotal") or 0)

    if not code:
        return error("Enter a promo code.")

    coupon = Coupon.query.filter_by(code=code).first()
    if not coupon or not coupon.is_valid():
        return error("Invalid or expired promo code.")

    discount = coupon.compute_discount(subtotal)
    return jsonify({"ok": True, "discount": discount, "code": coupon.code})


# ───────────────────────── public: checkout ─────────────────────────

@api_bp.route("/checkout", methods=["POST"])
def checkout():
    payload = request.get_json(silent=True) or {}
    cart_items = payload.get("items") or []
    channel = payload.get("channel", "whatsapp")
    coupon_code = (payload.get("coupon_code") or "").strip().upper() or None
    customer_name = (payload.get("customer_name") or "Guest").strip()[:120]
    customer_phone = (payload.get("customer_phone") or "").strip()[:30]

    if not cart_items:
        return error("Your cart is empty.")
    if channel not in ORDER_CHANNELS:
        channel = "whatsapp"

    subtotal = sum(int(i["price"]) * int(i["qty"]) for i in cart_items)
    delivery_fee = 0 if subtotal >= current_app.config["FREE_DELIVERY_THRESHOLD"] else current_app.config["DELIVERY_FEE"]
    tax = round(subtotal * current_app.config["TAX_RATE"])

    discount = 0
    if coupon_code:
        coupon = Coupon.query.filter_by(code=coupon_code).first()
        if coupon and coupon.is_valid():
            discount = coupon.compute_discount(subtotal)
            coupon.uses = (coupon.uses or 0) + 1

    total = max(subtotal + delivery_fee + tax - discount, 0)

    order = Order(
        order_number=Order.generate_order_number(),
        customer_name=customer_name or "Guest",
        customer_phone=customer_phone,
        channel=channel,
        status="pending",
        subtotal=subtotal,
        delivery_fee=delivery_fee,
        tax=tax,
        discount=discount,
        total=total,
        coupon_code=coupon_code if discount else None,
    )
    db.session.add(order)
    db.session.flush()  # get order.id before adding items

    for i in cart_items:
        db.session.add(
            OrderItem(
                order_id=order.id,
                menu_item_id=i.get("id"),
                name=i.get("name", "Item"),
                price=int(i.get("price", 0)),
                emoji=i.get("emoji", "🍽️"),
                qty=int(i.get("qty", 1)),
            )
        )

    db.session.commit()

    return jsonify(
        {
            "ok": True,
            "order_number": order.order_number,
            "total": order.total,
        }
    )


# ═══════════════════════ ADMIN JSON API (login required) ═══════════════════════

@api_bp.route("/admin/stats")
@login_required
def admin_stats():
    total_orders = Order.query.count()
    pending = Order.query.filter_by(status="pending").count()
    revenue = db.session.query(db.func.coalesce(db.func.sum(Order.total), 0)).scalar()
    menu_count = MenuItem.query.count()

    # last 7 days order counts for the mini bar chart
    from sqlalchemy import func

    daily = (
        db.session.query(func.date(Order.created_at), func.count(Order.id))
        .group_by(func.date(Order.created_at))
        .order_by(func.date(Order.created_at).desc())
        .limit(7)
        .all()
    )
    daily = list(reversed(daily))

    recent = Order.query.order_by(Order.created_at.desc()).limit(6).all()

    return jsonify(
        {
            "total_orders": total_orders,
            "pending_orders": pending,
            "revenue": revenue,
            "menu_count": menu_count,
            "daily": [{"label": str(d), "count": c} for d, c in daily],
            "recent_orders": [
                {
                    **o.to_dict(),
                    "customer_name": o.customer_name,
                }
                for o in recent
            ],
        }
    )


# ── Orders ──

@api_bp.route("/admin/orders")
@login_required
def admin_list_orders():
    status = request.args.get("status")
    q = Order.query
    if status and status in ORDER_STATUSES:
        q = q.filter_by(status=status)
    orders = q.order_by(Order.created_at.desc()).all()
    result = []
    for o in orders:
        d = o.to_dict()
        d["customer_name"] = o.customer_name
        d["items"] = [
            {"name": it.name, "qty": it.qty, "price": it.price} for it in o.items
        ]
        result.append(d)
    return jsonify(result)


@api_bp.route("/admin/orders/<int:order_id>/status", methods=["POST"])
@login_required
def admin_update_order_status(order_id):
    order = Order.query.get_or_404(order_id)
    payload = request.get_json(silent=True) or {}
    status = payload.get("status")
    if status not in ORDER_STATUSES:
        return error("Invalid status.")
    order.status = status
    db.session.commit()
    return jsonify({"ok": True})


# ── Menu editor ──

@api_bp.route("/admin/menu", methods=["GET", "POST"])
@login_required
def admin_menu_collection():
    if request.method == "GET":
        items = MenuItem.query.order_by(MenuItem.category_id, MenuItem.id).all()
        return jsonify([{**i.to_dict(), "category_id": i.category_id} for i in items])

    payload = request.get_json(silent=True) or {}
    name = (payload.get("name") or "").strip()
    price = payload.get("price")
    category_name = (payload.get("category") or "").strip()

    if not name or price is None or not category_name:
        return error("Name, price and category are required.")

    category = Category.query.filter_by(name=category_name).first()
    if not category:
        category = Category(name=category_name, sort_order=Category.query.count())
        db.session.add(category)
        db.session.flush()

    item = MenuItem(
        name=name,
        description=(payload.get("description") or "").strip(),
        price=int(price),
        emoji=(payload.get("emoji") or "🍽️").strip() or "🍽️",
        tag=(payload.get("tag") or "").strip(),
        category_id=category.id,
        is_available=True,
        in_stock=bool(payload.get("in_stock", True)),
        is_special=bool(payload.get("is_special", False)),
        image_data=(payload.get("image") or None),
    )
    db.session.add(item)
    db.session.commit()
    return jsonify({"ok": True, "item": {**item.to_dict(), "category_id": item.category_id}}), 201


@api_bp.route("/admin/menu/<int:item_id>", methods=["PUT", "DELETE"])
@login_required
def admin_menu_item(item_id):
    item = MenuItem.query.get_or_404(item_id)

    if request.method == "DELETE":
        db.session.delete(item)
        db.session.commit()
        return jsonify({"ok": True})

    payload = request.get_json(silent=True) or {}
    if "name" in payload:
        item.name = payload["name"].strip()
    if "description" in payload:
        item.description = payload["description"].strip()
    if "price" in payload:
        item.price = int(payload["price"])
    if "emoji" in payload:
        item.emoji = payload["emoji"].strip() or item.emoji
    if "tag" in payload:
        item.tag = payload["tag"].strip()
    if "category" in payload and payload["category"]:
        category = Category.query.filter_by(name=payload["category"]).first()
        if not category:
            category = Category(name=payload["category"], sort_order=Category.query.count())
            db.session.add(category)
            db.session.flush()
        item.category_id = category.id
    if "in_stock" in payload:
        item.in_stock = bool(payload["in_stock"])
    if "is_special" in payload:
        item.is_special = bool(payload["is_special"])
    if "image" in payload:
        item.image_data = payload["image"] or None

    db.session.commit()
    return jsonify({"ok": True, "item": {**item.to_dict(), "category_id": item.category_id}})


@api_bp.route("/admin/menu/<int:item_id>/toggle", methods=["POST"])
@login_required
def admin_toggle_menu_item(item_id):
    item = MenuItem.query.get_or_404(item_id)
    item.is_available = not item.is_available
    db.session.commit()
    return jsonify({"ok": True, "is_available": item.is_available})


@api_bp.route("/admin/menu/<int:item_id>/stock", methods=["POST"])
@login_required
def admin_toggle_stock(item_id):
    item = MenuItem.query.get_or_404(item_id)
    item.in_stock = not item.in_stock
    db.session.commit()
    return jsonify({"ok": True, "in_stock": item.in_stock})


@api_bp.route("/admin/menu/<int:item_id>/special", methods=["POST"])
@login_required
def admin_toggle_special(item_id):
    item = MenuItem.query.get_or_404(item_id)
    item.is_special = not item.is_special
    db.session.commit()
    return jsonify({"ok": True, "is_special": item.is_special})


# ── Coupons / Offers ──

@api_bp.route("/admin/coupons", methods=["GET", "POST"])
@login_required
def admin_coupons_collection():
    if request.method == "GET":
        coupons = Coupon.query.order_by(Coupon.id.desc()).all()
        return jsonify(
            [
                {
                    "id": c.id,
                    "code": c.code,
                    "description": c.description,
                    "discount_type": c.discount_type,
                    "value": c.value,
                    "uses": c.uses,
                    "max_uses": c.max_uses,
                    "expires_at": c.expires_at.strftime("%d %b %Y") if c.expires_at else None,
                    "active": c.active,
                    "is_valid": c.is_valid(),
                }
                for c in coupons
            ]
        )

    payload = request.get_json(silent=True) or {}
    code = (payload.get("code") or "").strip().upper()
    if not code:
        return error("Coupon code is required.")
    if Coupon.query.filter_by(code=code).first():
        return error("A coupon with that code already exists.")

    expires_at = None
    if payload.get("expires_at"):
        try:
            expires_at = datetime.strptime(payload["expires_at"], "%Y-%m-%d")
        except ValueError:
            pass

    coupon = Coupon(
        code=code,
        description=(payload.get("description") or "").strip(),
        discount_type=payload.get("discount_type", "percent"),
        value=int(payload.get("value", 0)),
        max_uses=payload.get("max_uses") or None,
        expires_at=expires_at,
        active=True,
    )
    db.session.add(coupon)
    db.session.commit()
    return jsonify({"ok": True}), 201


@api_bp.route("/admin/coupons/<int:coupon_id>", methods=["DELETE"])
@login_required
def admin_delete_coupon(coupon_id):
    coupon = Coupon.query.get_or_404(coupon_id)
    db.session.delete(coupon)
    db.session.commit()
    return jsonify({"ok": True})


@api_bp.route("/admin/coupons/<int:coupon_id>/toggle", methods=["POST"])
@login_required
def admin_toggle_coupon(coupon_id):
    coupon = Coupon.query.get_or_404(coupon_id)
    coupon.active = not coupon.active
    db.session.commit()
    return jsonify({"ok": True, "active": coupon.active})


# ── Site content ──

@api_bp.route("/admin/content", methods=["GET", "POST"])
@login_required
def admin_content():
    if request.method == "GET":
        rows = SiteContent.query.all()
        return jsonify({r.key: r.value for r in rows})

    payload = request.get_json(silent=True) or {}
    for key, value in payload.items():
        SiteContent.set(key, value)
    db.session.commit()
    return jsonify({"ok": True})


# ── Team / Chefs ──

@api_bp.route("/admin/team", methods=["GET", "POST"])
@login_required
def admin_team_collection():
    if request.method == "GET":
        members = TeamMember.query.order_by(TeamMember.sort_order, TeamMember.id).all()
        return jsonify([m.to_dict() for m in members])

    payload = request.get_json(silent=True) or {}
    name = (payload.get("name") or "").strip()
    if not name:
        return error("Name is required.")

    member = TeamMember(
        name=name,
        role=(payload.get("role") or "").strip(),
        avatar_emoji=(payload.get("avatar") or "👤").strip() or "👤",
        photo_data=(payload.get("photo") or None),
        sort_order=TeamMember.query.count(),
    )
    db.session.add(member)
    db.session.commit()
    return jsonify({"ok": True, "member": member.to_dict()}), 201


@api_bp.route("/admin/team/<int:member_id>", methods=["PUT", "DELETE"])
@login_required
def admin_team_member(member_id):
    member = TeamMember.query.get_or_404(member_id)

    if request.method == "DELETE":
        db.session.delete(member)
        db.session.commit()
        return jsonify({"ok": True})

    payload = request.get_json(silent=True) or {}
    if "name" in payload:
        member.name = payload["name"].strip()
    if "role" in payload:
        member.role = payload["role"].strip()
    if "avatar" in payload:
        member.avatar_emoji = payload["avatar"].strip() or member.avatar_emoji
    if "photo" in payload:
        member.photo_data = payload["photo"] or None

    db.session.commit()
    return jsonify({"ok": True, "member": member.to_dict()})
