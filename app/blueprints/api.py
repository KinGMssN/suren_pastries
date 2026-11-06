import base64
import binascii
import hashlib
import hmac
import json
import re
import secrets
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from functools import wraps
from io import BytesIO
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.table import Table, TableStyleInfo
from flask import Blueprint, current_app, g, jsonify, request, send_file, session
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import inspect as sqlalchemy_inspect
from sqlalchemy.exc import IntegrityError
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
    DashboardExportLog,
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


class RazorpayGatewayError(Exception):
    pass


def _razorpay_request(method, path, payload=None):
    key_id = current_app.config.get("RAZORPAY_KEY_ID")
    key_secret = current_app.config.get("RAZORPAY_KEY_SECRET")
    if not key_id or not key_secret:
        raise RazorpayGatewayError("Razorpay credentials are not configured.")

    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    gateway_request = Request(
        f"https://api.razorpay.com/v1/{path.lstrip('/')}",
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    gateway_request.add_header(
        "Authorization",
        "Basic " + base64.b64encode(f"{key_id}:{key_secret}".encode("utf-8")).decode("ascii"),
    )
    try:
        with urlopen(gateway_request, timeout=10) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RazorpayGatewayError(
            f"Razorpay request failed ({type(exc).__name__})."
        ) from exc
    if not isinstance(result, dict):
        raise RazorpayGatewayError("Razorpay returned an invalid response.")
    return result


def _order_payment_response(order):
    return {
        "ok": True,
        "key_id": current_app.config["RAZORPAY_KEY_ID"],
        "razorpay_order_id": order.razorpay_order_id,
        "amount": order.total * 100,
        "currency": "INR",
        "order_number": order.order_number,
        "customer_name": order.customer_name,
        "customer_phone": order.customer_phone,
    }


def _checkout_payment_action(payload, customer):
    action = payload.get("action")
    order_number = payload.get("order_number")
    if action not in {"create_payment", "verify_payment"}:
        return None
    if not isinstance(order_number, str):
        return error("Invalid order.")
    order = Order.query.filter_by(
        order_number=order_number.strip().upper(),
        customer_id=customer.id,
    ).first()
    if not order:
        return error("Order not found.", 404)
    if order.channel != "online":
        return error("This order does not use online payment.", 400)
    if order.payment_status == "paid":
        if action == "verify_payment":
            return jsonify({"ok": True, "payment_status": "paid"})
        return error("This order has already been paid.", 409)
    if order.status != "accepted":
        return error("Online payment is available after the admin accepts your order.", 409)
    if order.custom_cake_details and not order.quote_confirmed:
        return error("Confirm the cake quote before paying.", 409)

    if action == "create_payment":
        if order.total < 1:
            return error("This order cannot be paid online.", 400)
        if not current_app.config.get("RAZORPAY_KEY_ID") or not current_app.config.get("RAZORPAY_KEY_SECRET"):
            current_app.logger.error("Razorpay payment is unavailable because credentials are not configured.")
            return error("Online payments are temporarily unavailable.", 503)
        if not order.razorpay_order_id:
            try:
                gateway_order = _razorpay_request(
                    "POST",
                    "/orders",
                    {
                        "amount": order.total * 100,
                        "currency": "INR",
                        "receipt": order.order_number,
                        "notes": {"order_number": order.order_number},
                    },
                )
            except RazorpayGatewayError as exc:
                current_app.logger.error("Razorpay order creation failed: %s", exc)
                return error("Could not start online payment. Please try again.", 502)
            gateway_order_id = gateway_order.get("id")
            if (
                not isinstance(gateway_order_id, str)
                or not re.fullmatch(r"order_[A-Za-z0-9]+", gateway_order_id)
                or gateway_order.get("amount") != order.total * 100
                or gateway_order.get("currency") != "INR"
            ):
                current_app.logger.error("Razorpay returned an invalid order ID.")
                return error("Could not start online payment. Please try again.", 502)
            order.razorpay_order_id = gateway_order_id
            db.session.commit()
        return jsonify(_order_payment_response(order))

    payment_id = payload.get("razorpay_payment_id")
    signature = payload.get("razorpay_signature")
    if (
        not isinstance(payment_id, str)
        or not re.fullmatch(r"pay_[A-Za-z0-9]+", payment_id)
        or not isinstance(signature, str)
        or not re.fullmatch(r"[0-9a-fA-F]{64}", signature)
        or not order.razorpay_order_id
        or payload.get("razorpay_order_id") != order.razorpay_order_id
    ):
        return error("Invalid payment verification details.")
    if not current_app.config.get("RAZORPAY_KEY_SECRET"):
        current_app.logger.error("Razorpay payment verification is unavailable because credentials are not configured.")
        return error("Online payments are temporarily unavailable.", 503)

    expected_signature = hmac.new(
        current_app.config.get("RAZORPAY_KEY_SECRET", "").encode("utf-8"),
        f"{order.razorpay_order_id}|{payment_id}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected_signature, signature.lower()):
        return error("Payment verification failed.", 400)

    if order.razorpay_payment_id and order.razorpay_payment_id != payment_id:
        return error("A different payment is already associated with this order.", 409)

    try:
        payment = _razorpay_request("GET", f"/payments/{payment_id}")
        if (
            payment.get("order_id") != order.razorpay_order_id
            or payment.get("amount") != order.total * 100
            or payment.get("currency") != "INR"
        ):
            return error("The payment details do not match this order.", 400)
        if payment.get("status") == "authorized":
            try:
                _razorpay_request(
                    "POST",
                    f"/payments/{payment_id}/capture",
                    {"amount": order.total * 100, "currency": "INR"},
                )
            except RazorpayGatewayError as exc:
                current_app.logger.warning(
                    "Razorpay capture response was inconclusive (%s); checking payment state.",
                    type(exc).__name__,
                )
            payment = _razorpay_request("GET", f"/payments/{payment_id}")
    except RazorpayGatewayError as exc:
        current_app.logger.error("Razorpay payment verification failed: %s", exc)
        return error("Could not verify the payment right now. Please try again.", 502)

    if (
        payment.get("status") != "captured"
        or payment.get("order_id") != order.razorpay_order_id
        or payment.get("amount") != order.total * 100
        or payment.get("currency") != "INR"
    ):
        return error("Payment has not been captured yet. Please try again shortly.", 409)

    order.razorpay_payment_id = payment_id
    order.payment_status = "paid"
    order.status = "preparing"
    db.session.commit()
    return jsonify({"ok": True, "payment_status": "paid"})


def _validate_cake_reference_image(image):
    if image is None:
        return None
    if not isinstance(image, str):
        return None
    match = re.fullmatch(
        r"data:image/(jpeg|png|webp);base64,([A-Za-z0-9+/]*={0,2})",
        image,
    )
    if not match or len(match.group(2)) > 2_800_000:
        return None
    try:
        image_bytes = base64.b64decode(match.group(2), validate=True)
    except (binascii.Error, ValueError):
        return None
    if not image_bytes or len(image_bytes) > 2 * 1024 * 1024:
        return None

    image_type = match.group(1)
    is_valid_image = (
        image_type == "png" and image_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    ) or (
        image_type == "jpeg" and image_bytes.startswith(b"\xff\xd8\xff")
    ) or (
        image_type == "webp"
        and image_bytes.startswith(b"RIFF")
        and image_bytes[8:12] == b"WEBP"
    )
    return image if is_valid_image else None


def _create_custom_cake_request(payload, customer):
    description = payload.get("description")
    payment_method = payload.get("payment_method")
    required_date = payload.get("required_date")
    address_id = payload.get("address_id")
    if (
        not isinstance(description, str)
        or not description.strip()
        or len(description.strip()) > 1000
        or not isinstance(payment_method, str)
        or payment_method not in {"cod", "online"}
        or not isinstance(required_date, str)
        or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", required_date)
        or type(address_id) is not int
        or address_id < 1
    ):
        return error("Check the cake details, date, and delivery address.")
    reference_image = payload.get("reference_image")
    if reference_image is not None and _validate_cake_reference_image(reference_image) is None:
        return error("Upload one valid JPEG, PNG, or WebP cake photo up to 2 MB.")
    try:
        request_date = datetime.strptime(required_date, "%Y-%m-%d").date()
    except ValueError:
        return error("Choose a valid required date.")
    if request_date < datetime.utcnow().date():
        return error("The required date cannot be in the past.")

    address = CustomerAddress.query.filter_by(
        id=address_id,
        customer_id=customer.id,
    ).first()
    if not address:
        return error("Please select one of your saved delivery addresses.")

    idempotency_key = request.headers.get("Idempotency-Key", "")
    if not re.fullmatch(r"[A-Za-z0-9._:-]{16,64}", idempotency_key):
        return error("A valid request key is required.")
    existing_order = Order.query.filter_by(idempotency_key=idempotency_key).first()
    if existing_order:
        if existing_order.customer_id != customer.id:
            return error("This request key has already been used.", 409)
        return jsonify({"ok": True, "order_number": existing_order.order_number})

    active_order = _lock_customer_and_get_active_order(customer)
    existing_order = Order.query.filter_by(idempotency_key=idempotency_key).first()
    if existing_order:
        if existing_order.customer_id != customer.id:
            return error("This request key has already been used.", 409)
        return jsonify({"ok": True, "order_number": existing_order.order_number})
    if active_order:
        return _active_order_conflict(active_order)

    details = {
        "description": description.strip(),
        "required_date": request_date.isoformat(),
    }
    if reference_image:
        details["reference_image"] = reference_image
    order = Order(
        order_number=Order.generate_order_number(),
        idempotency_key=idempotency_key,
        customer_name=customer.name or "Guest",
        customer_phone=customer.phone,
        customer_id=customer.id,
        channel=payment_method,
        status="pending",
        payment_status="pending" if payment_method == "online" else "not_required",
        custom_cake_details=json.dumps(details),
        delivery_address=address.address_line,
        delivery_city=address.city,
        delivery_pincode=address.pincode,
        subtotal=0,
        delivery_fee=0,
        tax=0,
        discount=0,
        total=0,
    )
    db.session.add(order)
    db.session.flush()
    db.session.add(OrderItem(
        order_id=order.id,
        name="Custom cake request",
        price=0,
        emoji="🎂",
        qty=1,
    ))
    db.session.commit()
    return jsonify({"ok": True, "order_number": order.order_number})


def _confirm_custom_cake_quote(payload, customer):
    order_number = payload.get("order_number")
    if not isinstance(order_number, str):
        return error("Invalid cake order.")
    order = Order.query.filter_by(
        order_number=order_number.strip().upper(),
        customer_id=customer.id,
    ).first()
    if not order or not order.custom_cake_details:
        return error("Cake request not found.", 404)
    if order.status != "accepted" or order.total < 1:
        return error("The bakery has not set a quote for this cake yet.", 409)
    if order.quote_confirmed:
        return jsonify({"ok": True, "status": order.status})
    order.quote_confirmed = True
    if order.channel == "online":
        order.payment_status = "pending"
    else:
        order.status = "preparing"
    db.session.commit()
    return jsonify({"ok": True, "status": order.status})


def _normalize_phone(phone):
    return re.sub(r"\D", "", phone or "")


def _lock_customer_and_get_active_order(customer):
    db.session.execute(
        db.select(Customer.id)
        .where(Customer.id == customer.id)
        .with_for_update()
    ).scalar_one()
    return (
        Order.query.filter(
            Order.customer_id == customer.id,
            Order.status.notin_(("delivered", "rejected")),
        )
        .order_by(Order.created_at.desc(), Order.id.desc())
        .first()
    )


def _active_order_conflict(order):
    return jsonify({
        "ok": False,
        "active_order": {
            "order_number": order.order_number,
            "status": order.status,
        },
        "error": (
            f"You already have an active order ({order.order_number}). "
            "You can place another order after it is delivered or rejected."
        ),
    }), 409


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


def archive_before_delete(record, deleted_by_username=None, retained_fields=None):
    """Store a database-column snapshot before removing a record."""
    data = {}
    for column in sqlalchemy_inspect(record).mapper.columns:
        if retained_fields is not None and column.key not in retained_fields:
            continue
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
    except (binascii.Error, ValueError):
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
    archive_before_delete(
        customer,
        deleted_by_username=deleted_by,
        retained_fields={"name", "phone"},
    )
    Order.query.filter_by(customer_id=customer.id).update(
        {
            "customer_id": None,
            "customer_name": "Deleted customer",
            "customer_phone": "",
            "delivery_address": "",
            "delivery_city": "",
            "delivery_pincode": "",
        }
    )
    db.session.delete(customer)
    db.session.commit()
    session.pop("customer_id", None)
    return jsonify({"ok": True})


@api_bp.route("/customer/signup", methods=["POST"])
@limiter.limit("3 per minute")
def customer_signup():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return error("Invalid signup request.")

    phone_value = payload.get("phone")
    name = payload.get("name")
    password = payload.get("password")
    if not isinstance(phone_value, str) or not isinstance(name, str) or not isinstance(password, str):
        return error("Invalid signup request.")
    phone = _normalize_phone(phone_value)
    if len(phone) != 10:
        return error("Enter a valid 10-digit phone number.")

    name = name.strip()
    if not name or len(name) > 120:
        return error("Enter a name of 1 to 120 characters.")
    if not 8 <= len(password) <= 128:
        return error("Passwords must be between 8 and 128 characters.")
    customer = Customer.query.filter_by(phone=phone).with_for_update().first()
    if customer and customer.password_hash:
        return error("An account already exists for this phone number.", 409)

    if customer is None:
        customer = Customer(phone=phone, name=name)
        db.session.add(customer)
    elif not customer.name:
        customer.name = name
    customer.set_password(password)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return error("An account already exists for this phone number.", 409)
    session.pop("customer_id", None)
    session.permanent = True
    session["customer_id"] = customer.id
    return jsonify({"ok": True, "customer": customer.to_dict(include_addresses=False)})


@api_bp.route("/customer/login", methods=["POST"])
@limiter.limit("5 per minute")
def customer_login():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return error("Invalid login request.")
    phone_value = payload.get("phone")
    password = payload.get("password")
    if not isinstance(phone_value, str) or not isinstance(password, str):
        return error("Invalid login request.")
    phone = _normalize_phone(phone_value)
    if len(phone) != 10 or not 1 <= len(password) <= 128:
        return error("Enter a valid 10-digit phone number and password.")
    customer = Customer.query.filter_by(phone=phone).first()
    if not customer or not customer.check_password(password):
        return error("Invalid mobile number or password.", 401)
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


@api_bp.route("/customer/me")
def customer_me():
    customer = _get_current_customer()
    if not customer:
        session.pop("customer_id", None)
        return jsonify({"ok": True, "authenticated": False})
    return jsonify({
        "ok": True,
        "authenticated": True,
        "customer": customer.to_dict(include_addresses=False),
    })


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


@api_bp.route("/customer/active-order")
def customer_active_order():
    customer = _get_current_customer()
    if not customer:
        return error("Please log in first.", 401)
    order = (
        Order.query.filter(
            Order.customer_id == customer.id,
            Order.status.notin_(("delivered", "rejected")),
        )
        .order_by(Order.created_at.desc(), Order.id.desc())
        .first()
    )
    return jsonify({
        "ok": True,
        "active_order": (
            {"order_number": order.order_number, "status": order.status}
            if order else None
        ),
    })


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
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return error("Invalid coupon details.")
    code_value = payload.get("code", "")
    if not isinstance(code_value, str):
        return error("Coupon code is required.")
    code = code_value.strip().upper()
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
    if request.content_length and request.content_length > 3 * 1024 * 1024:
        return error("Cake photos must be 2 MB or smaller.", 413)
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return error("Invalid checkout details.")
    action = payload.get("action")
    if isinstance(action, str) and action in {
        "create_payment",
        "verify_payment",
        "custom_cake_request",
        "confirm_cake_quote",
    }:
        customer = _get_current_customer()
        if not customer:
            return error("Please log in to continue.", 401)
        if action == "custom_cake_request":
            return _create_custom_cake_request(payload, customer)
        if action == "confirm_cake_quote":
            return _confirm_custom_cake_quote(payload, customer)
        return _checkout_payment_action(payload, customer)

    cart_items = payload.get("items")
    channel = payload.get("channel", "whatsapp")
    coupon_code = payload.get("coupon_code") or ""
    phone_value = payload.get("phone")
    if not isinstance(coupon_code, str) or not isinstance(phone_value, str):
        return error("Invalid checkout details.")
    if not isinstance(channel, str) or channel not in ORDER_CHANNELS:
        return error("Invalid checkout method.")
    if channel == "whatsapp":
        return error("WhatsApp ordering is unavailable. Choose cash on delivery or online payment.", 503)
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

    active_order = _lock_customer_and_get_active_order(customer)
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
    if active_order:
        return _active_order_conflict(active_order)

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
        if item.stock_quantity is not None and item.stock_quantity < _quantity:
            return error(f"Not enough stock remains for {item.name}.", 409)

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

        for item_id, quantity in requested_items:
            item = menu_items[item_id]
            if item.stock_quantity is None:
                continue
            updated = MenuItem.query.filter(
                MenuItem.id == item_id,
                MenuItem.is_available.is_(True),
                MenuItem.in_stock.is_(True),
                MenuItem.stock_quantity >= quantity,
            ).update(
                {MenuItem.stock_quantity: MenuItem.stock_quantity - quantity},
                synchronize_session=False,
            )
            if updated != 1:
                db.session.rollback()
                return error("Stock changed while placing your order. Please try again.", 409)
            db.session.expire(item, ["stock_quantity"])
            if item.stock_quantity == 0:
                item.in_stock = False

        total = max(subtotal + delivery_fee + tax - discount, 0)
        order = Order(
            order_number=Order.generate_order_number(),
            idempotency_key=idempotency_key,
            customer_name=customer.name or "Guest",
            customer_phone=customer.phone,
            customer_id=customer.id,
            channel=channel,
            status="pending",
            payment_status="pending" if channel == "online" else "not_required",
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
    cake_details = (
        json.loads(order.custom_cake_details)
        if order.custom_cake_details else None
    )
    if cake_details:
        reference_image = cake_details.pop("reference_image", None)
        if reference_image:
            cake_details["has_reference_image"] = True
            if request.args.get("include_reference_image") == "1":
                cake_details["reference_image"] = reference_image
    return jsonify({
        "order_number": order.order_number,
        "channel": order.channel,
        "status": order.status,
        "payment_status": order.payment_status,
        "custom_cake_details": cake_details,
        "quote_confirmed": order.quote_confirmed,
        "rejection_message": "Your order is rejected." if order.status == "rejected" else None,
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
    latest_update = db.session.query(db.func.max(Order.updated_at)).scalar()
    last_export = DashboardExportLog.query.order_by(
        DashboardExportLog.downloaded_at.desc(),
        DashboardExportLog.id.desc(),
    ).first()

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
            "timestamps": {
                "last_updated_at": _dashboard_timestamp(latest_update),
                "last_download_at": _dashboard_timestamp(
                    last_export.downloaded_at if last_export else None
                ),
            },
        }
    )


def _dashboard_timestamp(value):
    return value.isoformat(timespec="seconds") + "Z" if value else None


def _safe_excel_text(value):
    value = str(value or "")
    if value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value


def _style_excel_sheet(sheet, widths):
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="8C3B22")
        cell.alignment = Alignment(vertical="center")
    sheet.row_dimensions[1].height = 24
    for column, width in widths.items():
        sheet.column_dimensions[column].width = width


def _dashboard_workbook(orders, menu_count, downloaded_at, last_download):
    workbook = Workbook()
    workbook.properties.creator = "Suren Pastries"
    workbook.properties.title = "Suren Pastries Dashboard Export"

    summary = workbook.active
    summary.title = "Dashboard"
    summary.merge_cells("A1:B1")
    summary["A1"] = "Suren Pastries — Dashboard Export"
    summary["A1"].font = Font(bold=True, size=16, color="FFFFFF")
    summary["A1"].fill = PatternFill("solid", fgColor="8C3B22")
    summary["A1"].alignment = Alignment(vertical="center")
    summary.row_dimensions[1].height = 32
    summary.append(["Timestamp", "Value"])
    summary.append(["Last updated", max(
        (order.updated_at or order.created_at for order in orders),
        default=None,
    )])
    summary.append(["Last downloaded", last_download])
    summary.append(["This download", downloaded_at])
    summary.append([])
    summary.append(["Dashboard metric", "Value"])
    summary.append(["Total revenue (INR)", sum(order.total or 0 for order in orders)])
    summary.append(["Total orders", len(orders)])
    summary.append([
        "Pending orders",
        sum(order.status == "pending" for order in orders),
    ])
    summary.append(["Active menu items", menu_count])
    for cell in summary[2]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="8C3B22")
    for row in (7,):
        for cell in summary[row]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="8C3B22")
    for row in (3, 4, 5):
        summary.cell(row, 2).number_format = "dd mmm yyyy hh:mm"
    summary["B8"].number_format = '"₹"#,##0.00'
    summary.column_dimensions["A"].width = 28
    summary.column_dimensions["B"].width = 28
    summary.freeze_panes = "A2"

    order_sheet = workbook.create_sheet("Orders")
    order_sheet.append([
        "Order number",
        "Customer",
        "Item count",
        "Total (INR)",
        "Status",
        "Created at",
        "Last updated",
        "Delivered at",
    ])
    item_sheet = workbook.create_sheet("Items")
    item_sheet.append([
        "Order number",
        "Customer",
        "Item",
        "Quantity",
        "Unit price (INR)",
        "Line total (INR)",
    ])
    for order in orders:
        order_sheet.append([
            _safe_excel_text(order.order_number),
            _safe_excel_text(order.customer_name),
            order.item_count(),
            order.total,
            _safe_excel_text(order.status.title()),
            order.created_at,
            order.updated_at or order.created_at,
            order.delivered_at,
        ])
        for item in order.items:
            item_sheet.append([
                _safe_excel_text(order.order_number),
                _safe_excel_text(order.customer_name),
                _safe_excel_text(item.name),
                item.qty,
                item.price,
                item.qty * item.price,
            ])

    _style_excel_sheet(order_sheet, {
        "A": 25, "B": 24, "C": 13, "D": 16,
        "E": 18, "F": 22, "G": 22, "H": 22,
    })
    _style_excel_sheet(item_sheet, {
        "A": 25, "B": 24, "C": 36, "D": 12, "E": 18, "F": 18,
    })
    for row in order_sheet.iter_rows(min_row=2):
        row[3].number_format = '"₹"#,##0.00'
        for cell in row[5:8]:
            cell.number_format = "dd mmm yyyy hh:mm"
    for row in item_sheet.iter_rows(min_row=2):
        row[4].number_format = '"₹"#,##0.00'
        row[5].number_format = '"₹"#,##0.00'

    for sheet in (order_sheet, item_sheet):
        if sheet.max_row > 1:
            table = Table(
                displayName=f"{sheet.title}Table",
                ref=sheet.dimensions,
            )
            table.tableStyleInfo = TableStyleInfo(
                name="TableStyleMedium2",
                showFirstColumn=False,
                showLastColumn=False,
                showRowStripes=True,
                showColumnStripes=False,
            )
            sheet.add_table(table)

    buffer = BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer


@api_bp.route("/admin/dashboard/export", methods=["POST"])
@login_required
@super_admin_required
def admin_dashboard_export():
    orders = Order.query.order_by(Order.created_at.desc(), Order.id.desc()).all()
    last_export = DashboardExportLog.query.order_by(
        DashboardExportLog.downloaded_at.desc(),
        DashboardExportLog.id.desc(),
    ).first()
    downloaded_at = datetime.utcnow()
    latest_update = max(
        (order.updated_at or order.created_at for order in orders),
        default=None,
    )
    workbook = _dashboard_workbook(
        orders,
        MenuItem.query.count(),
        downloaded_at,
        last_export.downloaded_at if last_export else None,
    )
    db.session.add(DashboardExportLog(
        downloaded_at=downloaded_at,
        admin_username=current_user.username,
    ))
    db.session.commit()

    return send_file(
        workbook,
        mimetype=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        ),
        as_attachment=True,
        download_name=(
            f"suren-pastries-dashboard-{downloaded_at.strftime('%Y%m%d-%H%M%S')}.xlsx"
        ),
        max_age=0,
    )


@api_bp.route("/admin/dashboard/reset", methods=["POST"])
@login_required
@super_admin_required
def admin_dashboard_reset():
    latest_update = db.session.query(
        db.func.max(db.func.coalesce(Order.updated_at, Order.created_at))
    ).scalar()
    last_export = DashboardExportLog.query.order_by(
        DashboardExportLog.downloaded_at.desc(),
        DashboardExportLog.id.desc(),
    ).first()
    if latest_update and (
        not last_export or last_export.downloaded_at < latest_update
    ):
        return error("Download a fresh dashboard export before resetting orders.", 409)

    order_count = Order.query.count()
    item_count = OrderItem.query.count()
    OrderItem.query.delete(synchronize_session=False)
    Order.query.delete(synchronize_session=False)
    db.session.commit()
    return jsonify({
        "ok": True,
        "deleted_orders": order_count,
        "deleted_items": item_count,
    })


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
            "data": {
                key: record.record_data[key]
                for key in ("name", "phone")
                if key in record.record_data
            } if record.table_name == "customers" else {},
            "deleted_by": record.deleted_by_username,
            "deleted_at": record.deleted_at.isoformat(),
        }
        for record in records
    ])


@api_bp.route("/admin/deleted-records/<int:record_id>", methods=["DELETE"])
@login_required
@super_admin_required
def admin_purge_deleted_record(record_id):
    record = DeletedRecord.query.get_or_404(record_id)
    db.session.delete(record)
    db.session.commit()
    return jsonify({"ok": True})


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
    try:
        reference_image_order_id = int(request.args.get("reference_image_order_id", ""))
    except ValueError:
        reference_image_order_id = None
    result = []
    for o in orders:
        d = o.to_dict()
        if o.id == reference_image_order_id and o.custom_cake_details:
            cake_details = json.loads(o.custom_cake_details)
            if cake_details.get("reference_image"):
                d["custom_cake_details"]["reference_image"] = cake_details["reference_image"]
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
    if status == "rejected":
        if order.status != "pending":
            return error("Only awaiting orders can be rejected.")
        if order.payment_status == "paid":
            return error("Paid orders cannot be rejected without a refund.")
        for order_item in order.items:
            item = db.session.get(MenuItem, order_item.menu_item_id) if order_item.menu_item_id else None
            if item and item.stock_quantity is not None:
                item.stock_quantity += order_item.qty
                item.in_stock = item.stock_quantity > 0
        order.status = "rejected"
        db.session.commit()
        return jsonify({"ok": True})

    if order.status == "pending":
        if order.custom_cake_details and status == "accepted":
            quote_total = payload.get("quote_total")
            if type(quote_total) is not int or not 1 <= quote_total <= 1000000:
                return error("Enter a cake quote between ₹1 and ₹1,000,000.")
            order.subtotal = quote_total
            order.delivery_fee = 0
            order.tax = 0
            order.discount = 0
            order.total = quote_total
            order.items[0].price = quote_total
            order.payment_status = "pending" if order.channel == "online" else "not_required"
            order.status = "accepted"
            db.session.commit()
            return jsonify({"ok": True})
        if order.channel == "online" and status == "accepted":
            order.status = "accepted"
            db.session.commit()
            return jsonify({"ok": True})
        if order.channel == "cod" and status == "preparing":
            order.status = "preparing"
            db.session.commit()
            return jsonify({"ok": True})
        if order.channel == "whatsapp":
            return error("Payment verification is not configured for this order.", 409)
        if order.channel == "online":
            return error("Accept the order before requesting payment.", 409)
        return error("Invalid order status transition.")

    valid_next_status = {
        "preparing": "ready",
        "ready": "delivered",
        "delivered": "delivered",
    }
    if status != valid_next_status.get(order.status):
        return error("Invalid order status transition.")
    if order.channel == "whatsapp":
        return error("Payment verification is not configured for this order.", 409)
    if order.channel == "online" and order.payment_status != "paid":
        return error("Payment must be verified before processing this order.", 409)
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
        return jsonify([
            {**i.to_dict(), "category_id": i.category_id, "stock_quantity": i.stock_quantity}
            for i in items
        ])

    payload = request.get_json(silent=True) or {}
    name = (payload.get("name") or "").strip()
    price = payload.get("price")
    category_name = (payload.get("category") or "").strip()
    stock_quantity = payload.get("stock_quantity")

    if not name or price is None or not category_name:
        return error("Name, price and category are required.")
    if type(stock_quantity) is not int or stock_quantity < 0:
        return error("Enter a non-negative stock quantity for new items.")

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
        in_stock=bool(payload.get("in_stock", True)) and stock_quantity > 0,
        stock_quantity=stock_quantity,
        is_special=bool(payload.get("is_special", False)),
        image_data=(payload.get("image") or None),
    )
    db.session.add(item)
    db.session.commit()
    return jsonify({
        "ok": True,
        "item": {
            **item.to_dict(),
            "category_id": item.category_id,
            "stock_quantity": item.stock_quantity,
        },
    }), 201


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
    if "stock_quantity" in payload:
        stock_quantity = payload["stock_quantity"]
        if stock_quantity is not None and (
            type(stock_quantity) is not int or stock_quantity < 0
        ):
            return error("Stock quantity must be a non-negative whole number or blank.")
        item.stock_quantity = stock_quantity
        if stock_quantity == 0:
            item.in_stock = False
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
    return jsonify({
        "ok": True,
        "item": {
            **item.to_dict(),
            "category_id": item.category_id,
            "stock_quantity": item.stock_quantity,
        },
    })


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
    if not item.in_stock and item.stock_quantity == 0:
        return error("Set a positive stock quantity before marking this item in stock.")
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
    expires_value = payload.get("expires_at")
    if expires_value is not None and not isinstance(expires_value, str):
        return error("Expiry date must use YYYY-MM-DD format.")
    if expires_value:
        try:
            expires_at = datetime.strptime(expires_value, "%Y-%m-%d")
        except ValueError:
            return error("Expiry date must use YYYY-MM-DD format.")

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
    q = q.filter(Order.status != "rejected")
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
    if order.channel == "whatsapp":
        return error("Payment verification is not configured for this order.", 409)
    if order.channel == "online" and order.payment_status != "paid":
        return error("Payment must be verified before assigning this order.", 409)
    person_id = payload.get("delivery_person_id")
    person = DeliveryPerson.query.filter_by(id=person_id, active=True).first() if person_id else None
    if not person:
        return error("Select an active delivery person.")
    if order.status != "ready":
        return error("Only ready orders can be assigned.")

    order.delivery_person_id = person.id
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
    if order.channel == "whatsapp":
        return error("Payment verification is not configured for this order.", 409)
    if order.channel == "online" and order.payment_status != "paid":
        return error("Payment must be verified before fulfilling this order.", 409)
    if order.channel == "cod" and payload.get("cod_collected") is not True:
        return error("Confirm that the COD payment was collected.")

    order.status = "delivered"
    order.delivered_at = datetime.utcnow()
    order.cod_collected = order.channel == "cod"

    db.session.commit()
    return jsonify({"ok": True})
