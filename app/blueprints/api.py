import base64
import re
import secrets
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from functools import wraps

from flask import Blueprint, current_app, g, jsonify, request, session
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import inspect as sqlalchemy_inspect
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db,limiter
from app.auth import verify_totp
from app.permissions import menu_access_required, super_admin_required
from app.models import (
    AdminUser,
    Category,
    Coupon,
    Customer,
    CustomerAddress,
    DeliveryPerson,
    DeletedRecord,
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


def _normalize_phone(phone):
    return re.sub(r"\D", "", phone or "")


def delivery_access_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user.is_authenticated:
            if getattr(current_user, "role", None) == "super_admin":
                g.delivery_admin = True
                g.delivery_person = None
                return view(*args, **kwargs)
            return error("Full admin access required.", 403)

        person_id = session.get("delivery_person_id")
        person = DeliveryPerson.query.filter_by(id=person_id, active=True).first() if person_id else None
        if not person:
            session.pop("delivery_person_id", None)
            return error("Delivery staff login required.", 401)
        g.delivery_admin = False
        g.delivery_person = person
        return view(*args, **kwargs)

    return wrapped


def _delivery_order_dict(order):
    return {
        "id": order.id,
        "order_number": order.order_number,
        "customer_name": order.customer_name,
        "customer_phone": order.customer_phone,
        "status": order.status,
        "channel": order.channel,
        "total": order.total,
        "delivery_address": order.delivery_address,
        "delivery_city": order.delivery_city,
        "delivery_pincode": order.delivery_pincode,
        "delivery_person_id": order.delivery_person_id,
        "delivery_person": order.delivery_person.name if order.delivery_person else None,
        "items": [
            {"name": item.name, "qty": item.qty, "price": item.price}
            for item in order.items
        ],
    }


def archive_before_delete(record, deleted_by_username=None):
    """Store a database-column snapshot before removing a record."""
    data = {}
    for column in sqlalchemy_inspect(record).mapper.columns:
        value = getattr(record, column.key)
        data[column.key] = value.isoformat() if isinstance(value, datetime) else value
    user = current_user if getattr(current_user, "is_authenticated", False) else None
    db.session.add(DeletedRecord(
        table_name=record.__tablename__,
        original_id=record.id,
        record_data=data,
        deleted_by_user_id=user.id if user else None,
        deleted_by_username=deleted_by_username or (user.username if user else None),
    ))


# ───────────────────────── image upload validation ─────────────────────────
ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/jpg"}
MAX_IMAGE_BYTES = 2 * 1024 * 1024


def validate_image_data_uri(data_uri):
    """Returns None if the value is empty or a valid small PNG/JPG data URI.
    Returns an error message string otherwise."""
    if not data_uri:
        return None
    match = re.match(r"^data:(image/[a-zA-Z0-9.+-]+);base64,(.+)$", data_uri, re.DOTALL)
    if not match:
        return "Invalid image format — please upload a PNG or JPG."
    mime_type, b64data = match.group(1).lower(), match.group(2)
    if mime_type not in ALLOWED_IMAGE_TYPES:
        return f"Unsupported image type ({mime_type}) — please use PNG or JPG."
    try:
        raw = base64.b64decode(b64data, validate=True)
    except Exception:
        return "Could not read that image — please try a different file."
    if len(raw) > MAX_IMAGE_BYTES:
        return f"Image is too large ({len(raw) // 1024}KB) — please use one under {MAX_IMAGE_BYTES // (1024 * 1024)}MB."
    return None


# ───────────────────────── auth (JSON, for the static frontend) ─────────────────────────

@api_bp.route("/auth/login", methods=["POST"])
@limiter.limit("5 per minute")
def auth_login():
    payload = request.get_json(silent=True) or {}
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""
    otp_code = str(payload.get("otp_code") or "").strip()

    user = AdminUser.query.filter_by(username=username).first()
    if user and user.locked_until and user.locked_until > datetime.utcnow():
        return error("This account is temporarily locked. Try again later.", 423)
    totp_required = current_app.config.get("ADMIN_TOTP_SECRET")
    if not user or not user.check_password(password) or (totp_required and not verify_totp(totp_required, otp_code)):
        if user:
            user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
            if user.failed_login_attempts >= current_app.config["ADMIN_MAX_LOGIN_FAILURES"]:
                from datetime import timedelta
                user.locked_until = datetime.utcnow() + timedelta(hours=24)
            db.session.commit()
        return error("Invalid username or password.", 401)

    user.failed_login_attempts = 0
    user.locked_until = None
    user.invalidate_sessions()
    db.session.commit()
    login_user(user)
    session.permanent = True
    session["admin_session_version"] = user.session_version
    session["admin_last_activity"] = datetime.utcnow().timestamp()
    return jsonify({"ok": True, "username": user.username})


@api_bp.route("/auth/logout", methods=["POST"])
@login_required
def auth_logout():
    logout_user()
    session.clear()
    return jsonify({"ok": True})


@api_bp.route("/auth/logout-everywhere", methods=["POST"])
@login_required
def auth_logout_everywhere():
    current_user.invalidate_sessions()
    db.session.commit()
    logout_user()
    session.clear()
    return jsonify({"ok": True})


@api_bp.route("/auth/reset-password", methods=["POST"])
@limiter.limit("3 per hour")
def auth_reset_password():
    payload = request.get_json(silent=True) or {}
    reset_key = payload.get("reset_key") or ""
    username = (payload.get("username") or "").strip()
    new_password = payload.get("new_password") or ""
    configured_key = current_app.config.get("ADMIN_RESET_KEY", "")
    if not configured_key or not secrets.compare_digest(reset_key, configured_key):
        return error("Password reset is not configured or the recovery key is invalid.", 403)
    if len(new_password) < 12:
        return error("New passwords must be at least 12 characters.")
    user = AdminUser.query.filter_by(username=username).first()
    if not user:
        return error("Password reset failed.", 400)
    user.set_password(new_password)
    user.failed_login_attempts = 0
    user.locked_until = None
    user.invalidate_sessions()
    db.session.commit()
    return jsonify({"ok": True})


@api_bp.route("/auth/me")
def auth_me():
    if current_user.is_authenticated:
        return jsonify({"ok": True, "authenticated": True, "username": current_user.username})
    return jsonify({"ok": True, "authenticated": False})




@api_bp.route("/customer/account", methods=["DELETE"])
def customer_delete_account():
    customer = _get_current_customer()
    if not customer:
        return error("Please log in first.", 401)

    deleted_by = f"customer:{customer.phone}"
    for address in list(customer.addresses):
        archive_before_delete(address, deleted_by_username=deleted_by)

    archive_before_delete(customer, deleted_by_username=deleted_by)
    Order.query.filter_by(customer_id=customer.id).update(
        {
            "customer_id": None,
            "customer_name": "Deleted customer",
            "customer_phone": "",
        }
    )
    db.session.delete(customer)
    db.session.commit()
    session.pop("customer_id", None)
    return jsonify({"ok": True})


@api_bp.route("/customer/request-otp", methods=["POST"])
@limiter.limit("3 per minute")
def customer_request_otp():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return error("Invalid verification request.")

    phone_value = payload.get("phone")
    mode = payload.get("mode")
    if not isinstance(phone_value, str) or not isinstance(mode, str) or mode not in {"login", "signup"}:
        return error("Invalid verification request.")
    phone = _normalize_phone(phone_value)
    if len(phone) != 10:
        return error("Enter a valid 10-digit phone number.")

    name = payload.get("name", "")
    if mode == "signup":
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 120:
            return error("Enter a name of 1 to 120 characters.")
        name = name.strip()

    customer = Customer.query.filter_by(phone=phone).first()
    if mode == "login" and not customer:
        return jsonify({"ok": False, "needs_name": True, "error": "No account found."}), 404
    if mode == "signup" and customer and not customer.otp_hash:
        return error("An account already exists for this phone number.", 409)

    debug_otp = current_app.config.get("CUSTOMER_OTP_DEBUG", False)
    sender = current_app.config.get("CUSTOMER_OTP_SENDER")
    if not debug_otp and not callable(sender):
        current_app.logger.error("Customer OTP delivery is not configured.")
        return error("Phone verification is temporarily unavailable.", 503)

    code = f"{secrets.randbelow(1_000_000):06d}"
    if customer is None:
        customer = Customer(phone=phone, name=name)
        db.session.add(customer)
    elif mode == "signup":
        customer.name = name
    customer.otp_hash = generate_password_hash(code)
    customer.otp_expires_at = datetime.utcnow() + timedelta(
        seconds=current_app.config.get("CUSTOMER_OTP_TTL_SECONDS", 600)
    )
    customer.otp_attempts = 0

    try:
        if not debug_otp:
            sender(phone, code)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error("Customer OTP delivery failed (%s).", type(exc).__name__)
        return error("Could not send a verification code. Please try again.", 502)

    response = {"ok": True}
    if debug_otp:
        response["debug_code"] = code
    return jsonify(response)


@api_bp.route("/customer/verify-otp", methods=["POST"])
@limiter.limit("10 per minute")
def customer_verify_otp():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return error("Invalid verification request.")
    phone_value = payload.get("phone")
    code = payload.get("code")
    if not isinstance(phone_value, str) or not isinstance(code, str):
        return error("Invalid verification request.")
    phone = _normalize_phone(phone_value)
    if len(phone) != 10 or not re.fullmatch(r"\d{6}", code):
        return error("Enter a valid phone number and six-digit code.")

    customer = Customer.query.filter_by(phone=phone).with_for_update().first()
    if not customer or not customer.otp_hash or not customer.otp_expires_at:
        return error("The verification code is invalid or expired.", 400)
    if customer.otp_expires_at <= datetime.utcnow():
        return error("The verification code has expired. Request a new one.", 400)
    if customer.otp_attempts >= 5:
        return error("Too many incorrect codes. Request a new one.", 429)
    if not check_password_hash(customer.otp_hash, code):
        customer.otp_attempts += 1
        db.session.commit()
        return error("The verification code is invalid or expired.", 400)

    customer.otp_hash = None
    customer.otp_expires_at = None
    customer.otp_attempts = 0
    db.session.commit()
    session.pop("customer_id", None)
    session.permanent = True
    session["customer_id"] = customer.id
    return jsonify({"ok": True, "customer": customer.to_dict(include_addresses=False)})


@api_bp.route("/customer/logout", methods=["POST"])
def customer_logout():
    session.pop("customer_id", None)
    return jsonify({"ok": True})


def _get_current_customer():
    customer_id = session.get("customer_id")
    return Customer.query.get(customer_id) if customer_id else None


@api_bp.route("/customer/addresses", methods=["GET", "POST"])
def customer_addresses():
    customer = _get_current_customer()
    if not customer:
        return error("Please log in first.", 401)

    if request.method == "GET":
        return jsonify([a.to_dict() for a in customer.addresses])

    payload = request.get_json(silent=True) or {}
    address_line = (payload.get("address_line") or "").strip()
    if not address_line:
        return error("Address is required.")

    if payload.get("is_default"):
        CustomerAddress.query.filter_by(customer_id=customer.id).update({"is_default": False})

    addr = CustomerAddress(
        customer_id=customer.id,
        label=(payload.get("label") or "Home").strip() or "Home",
        address_line=address_line,
        city=(payload.get("city") or "").strip(),
        pincode=(payload.get("pincode") or "").strip(),
        is_default=bool(payload.get("is_default")) or len(customer.addresses) == 0,
    )
    db.session.add(addr)
    db.session.commit()
    return jsonify({"ok": True, "address": addr.to_dict()}), 201


@api_bp.route("/customer/addresses/<int:address_id>", methods=["PUT", "DELETE"])
def customer_address_detail(address_id):
    addr = CustomerAddress.query.get_or_404(address_id)
    customer = _get_current_customer()
    if not customer:
        return error("Please log in first.", 401)
    if addr.customer_id != customer.id:
        return error("Address not found.", 404)

    if request.method == "DELETE":
        archive_before_delete(addr)
        db.session.delete(addr)
        db.session.commit()
        return jsonify({"ok": True})

    payload = request.get_json(silent=True) or {}
    if "label" in payload:
        addr.label = payload["label"].strip() or addr.label
    if "address_line" in payload:
        addr.address_line = payload["address_line"].strip()
    if "city" in payload:
        addr.city = payload["city"].strip()
    if "pincode" in payload:
        addr.pincode = payload["pincode"].strip()
    if payload.get("is_default"):
        CustomerAddress.query.filter_by(customer_id=addr.customer_id).update({"is_default": False})
        addr.is_default = True

    db.session.commit()
    return jsonify({"ok": True, "address": addr.to_dict()})


@api_bp.route("/customer/orders")
def customer_orders():
    customer = _get_current_customer()
    if not customer:
        return error("Please log in first.", 401)

    orders = (
        Order.query.filter_by(customer_id=customer.id)
        .order_by(Order.created_at.desc())
        .all()
    )
    result = []
    for o in orders:
        d = o.to_dict()
        d["items"] = [{"name": it.name, "qty": it.qty, "price": it.price} for it in o.items]
        result.append(d)
    return jsonify(result)


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
@limiter.limit("10 per minute")

def checkout():
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return error("Invalid checkout details.")
    cart_items = payload.get("items")
    channel = payload.get("channel", "whatsapp")
    coupon_code = payload.get("coupon_code") or ""
    phone_value = payload.get("phone")
    if not isinstance(coupon_code, str) or not isinstance(phone_value, str):
        return error("Invalid checkout details.")
    if not isinstance(channel, str) or channel not in ORDER_CHANNELS:
        return error("Invalid checkout method.")
    if channel == "online":
        return error("Online payments are not configured. Choose another checkout method.", 503)
    if channel == "whatsapp":
        return error("WhatsApp ordering is unavailable. Place a cash-on-delivery order instead.", 503)
    coupon_code = coupon_code.strip().upper() or None
    phone = _normalize_phone(phone_value)
    address_id = payload.get("address_id")
    if type(address_id) is not int or address_id < 1:
        return error("Please select a delivery address.")

    if not isinstance(cart_items, list) or not cart_items:
        return error("Your cart is empty.")
    if len(cart_items) > 50:
        return error("Your cart contains too many different items.")
    if len(phone) != 10:
        return error("Please log in to place an order.", 401)

    customer = _get_current_customer()
    if not customer:
        return error("Please log in to place an order.", 401)
    if phone and phone != customer.phone:
        return error("Please log in to place an order.", 401)

    idempotency_key = request.headers.get("Idempotency-Key", "")
    if not re.fullmatch(r"[A-Za-z0-9._:-]{16,64}", idempotency_key):
        return error("A valid checkout request key is required.")
    existing_order = Order.query.filter_by(idempotency_key=idempotency_key).first()
    if existing_order:
        if existing_order.customer_id != customer.id:
            return error("This checkout request key has already been used.", 409)
        return jsonify({
            "ok": True,
            "order_number": existing_order.order_number,
            "subtotal": existing_order.subtotal,
            "delivery_fee": existing_order.delivery_fee,
            "tax": existing_order.tax,
            "discount": existing_order.discount,
            "total": existing_order.total,
        })

    address = CustomerAddress.query.filter_by(id=address_id, customer_id=customer.id).first()
    if not address:
        return error("Please select a delivery address.")

    requested_items = []
    item_ids = set()
    for row in cart_items:
        if not isinstance(row, dict) or set(row) != {"item_id", "qty"}:
            return error("Each cart item must contain only an item ID and quantity.")
        item_id = row["item_id"]
        quantity = row["qty"]
        if type(item_id) is not int or item_id < 1:
            return error("Invalid menu item.")
        if type(quantity) is not int or not 1 <= quantity <= 20:
            return error("Item quantities must be whole numbers between 1 and 20.")
        if item_id in item_ids:
            return error("Each menu item may appear only once in the cart.")
        item_ids.add(item_id)
        requested_items.append((item_id, quantity))

    menu_items = {
        item.id: item
        for item in MenuItem.query.filter(MenuItem.id.in_(item_ids)).all()
    }
    if len(menu_items) != len(requested_items):
        return error("One or more menu items are no longer available.")
    for item_id, _quantity in requested_items:
        item = menu_items[item_id]
        if not item.is_available or not item.in_stock:
            return error(f"{item.name} is currently unavailable.")

    subtotal = sum(menu_items[item_id].price * quantity for item_id, quantity in requested_items)
    delivery_fee = 0 if subtotal >= current_app.config["FREE_DELIVERY_THRESHOLD"] else current_app.config["DELIVERY_FEE"]
    tax = int(
        (Decimal(subtotal) * Decimal(str(current_app.config["TAX_RATE"])))
        .quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )

    discount = 0
    try:
        if coupon_code:
            coupon = Coupon.query.filter_by(code=coupon_code).first()
            if coupon and coupon.is_valid():
                discount = coupon.compute_discount(subtotal)
                coupon.uses = (coupon.uses or 0) + 1

        total = max(subtotal + delivery_fee + tax - discount, 0)
        order = Order(
            order_number=Order.generate_order_number(),
            idempotency_key=idempotency_key,
            customer_name=customer.name or "Guest",
            customer_phone=customer.phone,
            customer_id=customer.id,
            channel=channel,
            status="pending",
            delivery_address=address.address_line,
            delivery_city=address.city,
            delivery_pincode=address.pincode,
            subtotal=subtotal,
            delivery_fee=delivery_fee,
            tax=tax,
            discount=discount,
            total=total,
            coupon_code=coupon_code if discount else None,
        )
        db.session.add(order)
        db.session.flush()

        for item_id, quantity in requested_items:
            item = menu_items[item_id]
            db.session.add(
                OrderItem(
                    order_id=order.id,
                    menu_item_id=item.id,
                    name=item.name,
                    price=item.price,
                    emoji=item.emoji,
                    qty=quantity,
                )
            )
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error("Checkout transaction failed (%s).", type(exc).__name__)
        existing_order = Order.query.filter_by(idempotency_key=idempotency_key).first()
        if existing_order and existing_order.customer_id == customer.id:
            return jsonify({
                "ok": True,
                "order_number": existing_order.order_number,
                "subtotal": existing_order.subtotal,
                "delivery_fee": existing_order.delivery_fee,
                "tax": existing_order.tax,
                "discount": existing_order.discount,
                "total": existing_order.total,
            })
        return error("Could not place your order. Please try again.", 500)

    return jsonify(
        {
            "ok": True,
            "order_number": order.order_number,
            "subtotal": order.subtotal,
            "delivery_fee": order.delivery_fee,
            "tax": order.tax,
            "discount": order.discount,
            "total": order.total,
        }
    )


# ───────────────────────── public: order tracking ─────────────────────────
@api_bp.route("/orders/track/<order_number>")
@limiter.limit("30 per minute")
def track_order(order_number):
    order = Order.query.filter_by(order_number=order_number.strip().upper()).first()
    if not order:
        return error("Order not found. Check the order number and try again.", 404)
    return jsonify({
        "order_number": order.order_number,
        "channel": order.channel,
        "status": order.status,
        "subtotal": order.subtotal,
        "delivery_fee": order.delivery_fee,
        "tax": order.tax,
        "discount": order.discount,
        "total": order.total,
        "created_at": order.created_at.strftime("%d %b %Y, %I:%M %p"),
        "delivered_at": (
            order.delivered_at.strftime("%d %b %Y, %I:%M %p")
            if order.delivered_at else None
        ),
        "has_delivery_person": bool(order.delivery_person_id),
        "items": [
            {"name": item.name, "qty": item.qty, "price": item.price}
            for item in order.items
        ],
    })


@api_bp.route("/delivery/orders/<int:order_id>")
@delivery_access_required
def delivery_order_detail(order_id):
    order = Order.query.get_or_404(order_id)
    if not g.delivery_admin and order.delivery_person_id != g.delivery_person.id:
        return error("Order not found.", 404)
    return jsonify(_delivery_order_dict(order))


# ═══════════════════════ ADMIN JSON API (login required) ═══════════════════════

@api_bp.route("/admin/stats")
@login_required
@super_admin_required
def admin_stats():
    total_orders = Order.query.count()
    pending = Order.query.filter_by(status="pending").count()
    revenue = db.session.query(db.func.coalesce(db.func.sum(Order.total), 0)).scalar()
    menu_count = MenuItem.query.count()

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


@api_bp.route("/admin/deleted-records")
@login_required
@super_admin_required
def admin_deleted_records():
    records = DeletedRecord.query.order_by(DeletedRecord.deleted_at.desc()).limit(500).all()
    return jsonify([
        {
            "id": record.id,
            "table": record.table_name,
            "original_id": record.original_id,
            "data": record.record_data,
            "deleted_by": record.deleted_by_username,
            "deleted_at": record.deleted_at.isoformat(),
        }
        for record in records
    ])


# ── Orders ──

@api_bp.route("/admin/orders")
@login_required
@super_admin_required
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
@super_admin_required
def admin_update_order_status(order_id):
    order = Order.query.get_or_404(order_id)
    payload = request.get_json(silent=True) or {}
    status = payload.get("status")
    if status not in ORDER_STATUSES:
        return error("Invalid status.")
    valid_next_status = {
        "pending": "preparing",
        "preparing": "ready",
        "ready": "delivered",
        "delivered": "delivered",
    }
    if status != valid_next_status.get(order.status):
        return error("Invalid order status transition.")
    if order.channel in {"online", "whatsapp"}:
        return error("Payment verification is not configured for this order.", 409)
    if status == "delivered" and order.channel == "cod" and payload.get("cod_collected") is not True:
        return error("Confirm that the COD payment was collected.")
    order.status = status
    if status == "delivered":
        order.delivered_at = datetime.utcnow()
        order.cod_collected = order.channel == "cod"
    db.session.commit()
    return jsonify({"ok": True})


# ── Menu editor ──

@api_bp.route("/admin/menu", methods=["GET", "POST"])
@login_required
@menu_access_required
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

    img_error = validate_image_data_uri(payload.get("image"))
    if img_error:
        return error(img_error)

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
@menu_access_required
def admin_menu_item(item_id):
    item = MenuItem.query.get_or_404(item_id)

    if request.method == "DELETE":
        OrderItem.query.filter_by(menu_item_id=item.id).update({"menu_item_id": None})
        archive_before_delete(item)
        db.session.delete(item)
        db.session.commit()
        return jsonify({"ok": True})

    payload = request.get_json(silent=True) or {}
    if "image" in payload:
        img_error = validate_image_data_uri(payload["image"])
        if img_error:
            return error(img_error)
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
@menu_access_required
def admin_toggle_menu_item(item_id):
    item = MenuItem.query.get_or_404(item_id)
    item.is_available = not item.is_available
    db.session.commit()
    return jsonify({"ok": True, "is_available": item.is_available})


@api_bp.route("/admin/menu/<int:item_id>/stock", methods=["POST"])
@login_required
@menu_access_required
def admin_toggle_stock(item_id):
    item = MenuItem.query.get_or_404(item_id)
    item.in_stock = not item.in_stock
    db.session.commit()
    return jsonify({"ok": True, "in_stock": item.in_stock})


@api_bp.route("/admin/menu/<int:item_id>/special", methods=["POST"])
@login_required
@menu_access_required
def admin_toggle_special(item_id):
    item = MenuItem.query.get_or_404(item_id)
    item.is_special = not item.is_special
    db.session.commit()
    return jsonify({"ok": True, "is_special": item.is_special})


# ── Coupons / Offers ──

@api_bp.route("/admin/coupons", methods=["GET", "POST"])
@login_required
@super_admin_required
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
@super_admin_required
def admin_delete_coupon(coupon_id):
    coupon = Coupon.query.get_or_404(coupon_id)
    archive_before_delete(coupon)
    db.session.delete(coupon)
    db.session.commit()
    return jsonify({"ok": True})


@api_bp.route("/admin/coupons/<int:coupon_id>/toggle", methods=["POST"])
@login_required
@super_admin_required
def admin_toggle_coupon(coupon_id):
    coupon = Coupon.query.get_or_404(coupon_id)
    coupon.active = not coupon.active
    db.session.commit()
    return jsonify({"ok": True, "active": coupon.active})


# ── Site content ──

@api_bp.route("/admin/content", methods=["GET", "POST"])
@login_required
@super_admin_required
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

@api_bp.route("/team")
def public_team():
    members = TeamMember.query.order_by(TeamMember.sort_order, TeamMember.id).all()
    return jsonify([
        {
            "name": member.name,
            "role": member.role,
            "avatar": member.avatar_emoji,
            "photo": member.photo_data or None,
        }
        for member in members
    ])


@api_bp.route("/admin/team", methods=["GET", "POST"])
@login_required
@super_admin_required
def admin_team_collection():
    if request.method == "GET":
        members = TeamMember.query.order_by(TeamMember.sort_order, TeamMember.id).all()
        return jsonify([m.to_dict() for m in members])

    payload = request.get_json(silent=True) or {}
    name = (payload.get("name") or "").strip()
    if not name:
        return error("Name is required.")

    img_error = validate_image_data_uri(payload.get("photo"))
    if img_error:
        return error(img_error)

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
@super_admin_required
def admin_team_member(member_id):
    member = TeamMember.query.get_or_404(member_id)

    if request.method == "DELETE":
        archive_before_delete(member)
        db.session.delete(member)
        db.session.commit()
        return jsonify({"ok": True})

    payload = request.get_json(silent=True) or {}
    if "photo" in payload:
        img_error = validate_image_data_uri(payload["photo"])
        if img_error:
            return error(img_error)
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



# ── Delivery staff roster (admin manages who's on the team) ──

@api_bp.route("/admin/delivery-people", methods=["GET", "POST"])
@login_required
@super_admin_required
def admin_delivery_people():
    if request.method == "GET":
        people = DeliveryPerson.query.order_by(DeliveryPerson.name).all()
        return jsonify([p.to_dict() for p in people])

    payload = request.get_json(silent=True) or {}
    name = (payload.get("name") or "").strip()
    if not name:
        return error("Name is required.")
    if DeliveryPerson.query.filter(db.func.lower(DeliveryPerson.name) == name.lower()).first():
        return error("A delivery person with that name already exists.")

    person = DeliveryPerson(
        name=name,
        phone=(payload.get("phone") or "").strip(),
        active=True,
    )
    password = payload.get("password") or ""
    if not isinstance(password, str) or len(password) < 12:
        return error("A delivery password of at least 12 characters is required.")
    person.set_password(password)
    db.session.add(person)
    db.session.commit()
    return jsonify({"ok": True, "person": person.to_dict()}), 201


@api_bp.route("/admin/delivery-people/<int:person_id>", methods=["PUT", "DELETE"])
@login_required
@super_admin_required
def admin_delivery_person_detail(person_id):
    person = DeliveryPerson.query.get_or_404(person_id)

    if request.method == "DELETE":
        archive_before_delete(person)
        db.session.delete(person)
        db.session.commit()
        return jsonify({"ok": True})

    payload = request.get_json(silent=True) or {}
    if "name" in payload:
        name = payload["name"].strip()
        duplicate = DeliveryPerson.query.filter(
            db.func.lower(DeliveryPerson.name) == name.lower(),
            DeliveryPerson.id != person.id,
        ).first()
        if not name or duplicate:
            return error("A unique delivery person name is required.")
        person.name = name
    if "phone" in payload:
        person.phone = payload["phone"].strip()
    if "password" in payload and payload["password"]:
        if not isinstance(payload["password"], str) or len(payload["password"]) < 12:
            return error("A delivery password must be at least 12 characters.")
        person.set_password(payload["password"])

    db.session.commit()
    return jsonify({"ok": True, "person": person.to_dict()})


@api_bp.route("/admin/delivery-people/<int:person_id>/toggle", methods=["POST"])
@login_required
@super_admin_required
def admin_toggle_delivery_person(person_id):
    person = DeliveryPerson.query.get_or_404(person_id)
    person.active = not person.active
    db.session.commit()
    return jsonify({"ok": True, "active": person.active})


# ═════════════════════════════ DELIVERY PORTAL ══════════════════════════════

@api_bp.route("/delivery/login", methods=["POST"])
@limiter.limit("5 per minute")
def delivery_login():
    payload = request.get_json(silent=True) or {}
    name = (payload.get("name") or "").strip()
    password = payload.get("password") or ""
    person = DeliveryPerson.query.filter_by(name=name, active=True).first()
    if not person or not person.check_password(password):
        return error("Invalid delivery login.", 401)

    session.clear()
    session.permanent = True
    session["delivery_person_id"] = person.id
    return jsonify({"ok": True, "name": person.name})


@api_bp.route("/delivery/logout", methods=["POST"])
@delivery_access_required
def delivery_logout():
    session.clear()
    return jsonify({"ok": True})

@api_bp.route("/delivery/people")
@delivery_access_required
def delivery_people_list():
    if not g.delivery_admin:
        return error("Full admin access required.", 403)
    people = DeliveryPerson.query.filter_by(active=True).order_by(DeliveryPerson.name).all()
    return jsonify([p.to_dict() for p in people])


@api_bp.route("/delivery/orders")
@delivery_access_required
def delivery_orders_list():
    q = Order.query.filter(Order.status != "delivered")
    if not g.delivery_admin:
        q = q.filter(Order.delivery_person_id == g.delivery_person.id)
    orders = q.order_by(Order.created_at.asc()).all()
    return jsonify([_delivery_order_dict(order) for order in orders])


@api_bp.route("/delivery/orders/<int:order_id>/assign", methods=["POST"])
@delivery_access_required
def delivery_assign_order(order_id):
    if not g.delivery_admin:
        return error("Full admin access required.", 403)
    order = Order.query.get_or_404(order_id)
    payload = request.get_json(silent=True) or {}
    if order.channel in {"online", "whatsapp"}:
        return error("Payment verification is not configured for this order.", 409)
    person_id = payload.get("delivery_person_id")
    person = DeliveryPerson.query.filter_by(id=person_id, active=True).first() if person_id else None
    if not person:
        return error("Select an active delivery person.")
    if order.status not in {"pending", "preparing"}:
        return error("Only pending or preparing orders can be assigned.")

    order.delivery_person_id = person.id
    if order.status == "pending":
        order.status = "preparing"
    db.session.commit()
    return jsonify({"ok": True})


@api_bp.route("/delivery/orders/<int:order_id>/deliver", methods=["POST"])
@delivery_access_required
def delivery_mark_delivered(order_id):
    order = Order.query.get_or_404(order_id)
    payload = request.get_json(silent=True) or {}

    if not g.delivery_admin and order.delivery_person_id != g.delivery_person.id:
        return error("Order is not assigned to this delivery person.", 403)
    if order.status != "ready":
        return error("Only ready orders can be marked delivered.")
    if order.channel in {"online", "whatsapp"}:
        return error("Payment verification is not configured for this order.", 409)
    if order.channel == "cod" and payload.get("cod_collected") is not True:
        return error("Confirm that the COD payment was collected.")

    order.status = "delivered"
    order.delivered_at = datetime.utcnow()
    order.cod_collected = order.channel == "cod"

    db.session.commit()
    return jsonify({"ok": True})
