from datetime import datetime, timedelta
import hashlib
import hmac
import secrets

import pytest

from app.extensions import db
from app.blueprints import api as api_module
from app.models import (
    AdminUser,
    Category,
    Coupon,
    Customer,
    CustomerAddress,
    DeliveryPerson,
    MenuItem,
    Order,
    OrderItem,
    SiteContent,
    TeamMember,
)


def create_order(person=None, status="ready", channel="cod"):
    order = Order(
        order_number="SPTEST" + secrets.token_hex(4).upper(),
        customer_name="Test Customer",
        customer_phone="1234567890",
        channel=channel,
        payment_status="pending" if channel == "online" else "not_required",
        status=status,
        delivery_address="1 Test Street",
        delivery_city="Test City",
        delivery_pincode="123456",
        delivery_person=person,
        subtotal=100,
        delivery_fee=40,
        tax=5,
        total=145,
    )
    db.session.add(order)
    db.session.flush()
    db.session.add(OrderItem(
        order_id=order.id,
        name="Test pastry",
        price=100,
        qty=1,
    ))
    db.session.commit()
    return order


def test_delivery_endpoints_require_authentication_and_limit_orders(app, client):
    with app.app_context():
        person = DeliveryPerson(name="Assigned Courier", active=True)
        person.set_password("a-long-test-password")
        db.session.add(person)
        order = create_order(person)
        other_order = create_order(status="ready")
        order_id = order.id
        other_order_id = other_order.id

    assert client.get("/api/delivery/orders").status_code == 401
    assert client.get(f"/api/delivery/orders/{order_id}").status_code == 401
    assert client.get("/api/delivery/people").status_code == 401
    assert client.post(
        f"/api/delivery/orders/{order_id}/assign",
        json={"delivery_person_id": 1},
    ).status_code == 401
    assert client.post(
        f"/api/delivery/orders/{order_id}/deliver",
        json={"cod_collected": True},
    ).status_code == 401

    login = client.post(
        "/api/delivery/login",
        json={"name": "Assigned Courier", "password": "a-long-test-password"},
    )
    assert login.status_code == 200

    orders = client.get("/api/delivery/orders").get_json()
    assert [row["id"] for row in orders] == [order_id]
    assert client.get(f"/api/delivery/orders/{other_order_id}").status_code == 404
    assert client.post(
        f"/api/delivery/orders/{other_order_id}/deliver",
        json={"cod_collected": True},
    ).status_code == 403
    assert client.post(
        f"/api/delivery/orders/{order_id}/assign",
        json={"delivery_person_id": 1},
    ).status_code == 403
    missing_confirmation = client.post(
        f"/api/delivery/orders/{order_id}/deliver",
        json={"cod_collected": False},
    )
    assert missing_confirmation.status_code == 400
    delivered = client.post(
        f"/api/delivery/orders/{order_id}/deliver",
        json={"cod_collected": True},
    )
    assert delivered.status_code == 200


def test_admin_can_assign_and_cod_requires_confirmation(app, client):
    with app.app_context():
        admin = AdminUser(username="test-admin", role="super_admin")
        admin.set_password("test-admin-password")
        person = DeliveryPerson(name="Admin Assigned Courier", active=True)
        person.set_password("a-different-test-password")
        db.session.add_all([admin, person])
        db.session.flush()
        order = create_order(status="pending")
        order_id = order.id
        person_id = person.id

    login = client.post(
        "/admin/login",
        data={"username": "test-admin", "password": "test-admin-password"},
    )
    assert login.status_code == 302
    assert client.get("/api/delivery/people").status_code == 200
    ready = client.post(
        f"/api/admin/orders/{order_id}/status",
        json={"status": "ready"},
    )
    assert ready.status_code == 400
    accepted = client.post(
        f"/api/admin/orders/{order_id}/status",
        json={"status": "preparing"},
    )
    assert accepted.status_code == 200
    not_ready = client.post(
        f"/api/delivery/orders/{order_id}/assign",
        json={"delivery_person_id": person_id},
    )
    assert not_ready.status_code == 400

    mark_ready = client.post(
        f"/api/admin/orders/{order_id}/status",
        json={"status": "ready"},
    )
    assert mark_ready.status_code == 200
    assigned = client.post(
        f"/api/delivery/orders/{order_id}/assign",
        json={"delivery_person_id": person_id},
    )
    assert assigned.status_code == 200
    missing_confirmation = client.post(
        f"/api/admin/orders/{order_id}/status",
        json={"status": "delivered", "cod_collected": False},
    )
    assert missing_confirmation.status_code == 400
    delivered = client.post(
        f"/api/admin/orders/{order_id}/status",
        json={"status": "delivered", "cod_collected": True},
    )
    assert delivered.status_code == 200


def test_admin_can_export_dashboard_and_reset_only_orders(app, client):
    with app.app_context():
        admin = AdminUser(username="dashboard-admin", role="super_admin")
        admin.set_password("dashboard-admin-password")
        customer = Customer(phone="1234567890", name="Dashboard Customer")
        category = Category(name="Dashboard pastries")
        db.session.add_all([admin, customer, category])
        db.session.flush()
        menu_item = MenuItem(
            name="Dashboard pastry",
            price=145,
            category_id=category.id,
            is_available=True,
        )
        db.session.add(menu_item)
        order = create_order(status="ready")
        order_id = order.id
        customer_id = customer.id
        menu_item_id = menu_item.id

    client.post(
        "/admin/login",
        data={"username": "dashboard-admin", "password": "dashboard-admin-password"},
    )
    reset_without_export = client.post("/api/admin/dashboard/reset")
    assert reset_without_export.status_code == 409

    first_download = client.post("/api/admin/dashboard/export")
    assert first_download.status_code == 200
    assert "attachment;" in first_download.headers["Content-Disposition"]
    first_report = first_download.get_json()
    assert first_report["dashboard"] == {
        "total_revenue": 145,
        "total_orders": 1,
        "pending_orders": 0,
        "active_menu_items": 1,
        "recent_orders": first_report["orders"],
    }
    assert first_report["timestamps"]["last_updated_at"]
    assert first_report["timestamps"]["last_download_at"] is None
    assert first_report["timestamps"]["this_download_at"]
    assert first_report["orders"][0]["order_number"]
    assert first_report["orders"][0]["items"] == [
        {"name": "Test pastry", "quantity": 1, "price": 100}
    ]

    second_report = client.post("/api/admin/dashboard/export").get_json()
    assert second_report["timestamps"]["last_download_at"] == (
        first_report["timestamps"]["this_download_at"]
    )

    reset = client.post("/api/admin/dashboard/reset")
    assert reset.status_code == 200
    assert reset.get_json() == {
        "ok": True,
        "deleted_orders": 1,
        "deleted_items": 1,
    }
    with app.app_context():
        assert Order.query.count() == 0
        assert OrderItem.query.count() == 0
        assert db.session.get(Customer, customer_id) is not None
        assert db.session.get(MenuItem, menu_item_id) is not None
    stats = client.get("/api/admin/stats").get_json()
    assert stats["total_orders"] == 0
    assert stats["revenue"] == 0
    assert stats["menu_count"] == 1


def test_admin_rejection_is_terminal_and_visible_to_customer(app, client):
    with app.app_context():
        admin = AdminUser(username="reject-admin", role="super_admin")
        admin.set_password("reject-admin-password")
        customer = Customer(phone="1234567890", name="Rejected Customer")
        db.session.add_all([admin, customer])
        db.session.flush()
        order = create_order(status="pending")
        order.customer_id = customer.id
        order_id = order.id
        order_number = order.order_number
        customer_id = customer.id
        db.session.commit()

    login = client.post(
        "/admin/login",
        data={"username": "reject-admin", "password": "reject-admin-password"},
    )
    assert login.status_code == 302
    rejected = client.post(
        f"/api/admin/orders/{order_id}/status",
        json={"status": "rejected"},
    )
    assert rejected.status_code == 200
    assert client.post(
        f"/api/admin/orders/{order_id}/status",
        json={"status": "preparing"},
    ).status_code == 400

    tracked = client.get(f"/api/orders/track/{order_number}").get_json()
    assert tracked["status"] == "rejected"
    assert tracked["rejection_message"] == "Your order is rejected."
    with client.session_transaction() as browser_session:
        browser_session["customer_id"] = customer_id
    history = client.get("/api/customer/orders").get_json()
    assert history[0]["status"] == "rejected"

    with app.app_context():
        assert db.session.get(Order, order_id).status == "rejected"


def test_delivery_requires_ready_status_and_cod_confirmation(app, client):
    with app.app_context():
        person = DeliveryPerson(name="Ready Courier", active=True)
        person.set_password("another-long-test-password")
        db.session.add(person)
        order = create_order(person, status="preparing")
        order_id = order.id

    assert client.post(
        "/api/delivery/login",
        json={"name": "Ready Courier", "password": "another-long-test-password"},
    ).status_code == 200
    response = client.post(
        f"/api/delivery/orders/{order_id}/deliver",
        json={"cod_collected": True},
    )
    assert response.status_code == 400
    assert response.get_json()["error"] == "Only ready orders can be marked delivered."


def test_checkout_rejects_client_prices_and_invalid_quantities(app, client):
    with app.app_context():
        category = Category(name="Test category")
        customer = Customer(phone="1234567890", name="Test Customer")
        db.session.add_all([category, customer])
        db.session.flush()
        item = MenuItem(
            name="Server-priced pastry",
            price=120,
            emoji="🥐",
            category_id=category.id,
            is_available=True,
            in_stock=True,
        )
        address = CustomerAddress(
            customer_id=customer.id,
            address_line="1 Test Street",
            city="Test City",
            pincode="123456",
            is_default=True,
        )
        db.session.add_all([item, address])
        db.session.commit()
        customer_id = customer.id
        item_id = item.id
        address_id = address.id

    with client.session_transaction() as browser_session:
        browser_session["customer_id"] = customer_id

    def submit(items):
        return client.post(
            "/api/checkout",
            json={
                "items": items,
                "channel": "cod",
                "phone": "1234567890",
                "address_id": address_id,
            },
            headers={"Idempotency-Key": "test-checkout-request-key-001"},
        )

    assert submit([{"item_id": item_id, "qty": 1, "price": 1}]).status_code == 400
    assert submit([{"item_id": item_id, "qty": 0}]).status_code == 400
    assert submit([{"item_id": item_id, "qty": "1"}]).status_code == 400

    response = submit([{"item_id": item_id, "qty": 1}])
    assert response.status_code == 200
    assert response.get_json()["total"] == 166
    retry = submit([{"item_id": item_id, "qty": 1}])
    assert retry.status_code == 200
    assert retry.get_json()["order_number"] == response.get_json()["order_number"]
    with app.app_context():
        created = Order.query.one()
        assert created.subtotal == 120
        assert created.items[0].name == "Server-priced pastry"
        assert created.items[0].price == 120


def test_checkout_rolls_back_order_when_commit_fails(app, client, monkeypatch):
    from sqlalchemy.orm import Session

    with app.app_context():
        category = Category(name="Atomic category")
        customer = Customer(phone="1234567890", name="Atomic Customer")
        db.session.add_all([category, customer])
        db.session.flush()
        item = MenuItem(
            name="Atomic pastry",
            price=100,
            category_id=category.id,
            is_available=True,
            in_stock=True,
            stock_quantity=2,
        )
        address = CustomerAddress(customer_id=customer.id, address_line="Atomic address")
        db.session.add_all([item, address])
        db.session.commit()
        customer_id = customer.id
        item_id = item.id
        address_id = address.id

    with client.session_transaction() as browser_session:
        browser_session["customer_id"] = customer_id

    def fail_commit(_self):
        raise RuntimeError("simulated commit failure")

    monkeypatch.setattr(Session, "commit", fail_commit)
    response = client.post(
        "/api/checkout",
        json={
            "items": [{"item_id": item_id, "qty": 1}],
            "channel": "cod",
            "phone": "1234567890",
            "address_id": address_id,
        },
        headers={"Idempotency-Key": "test-atomic-checkout-key-001"},
    )
    assert response.status_code == 500
    monkeypatch.undo()

    with app.app_context():
        assert Order.query.count() == 0
        assert OrderItem.query.count() == 0
        item = db.session.get(MenuItem, item_id)
        assert item.stock_quantity == 2
        assert item.in_stock is True


def test_tax_and_percent_discount_round_half_up(app, client):
    with app.app_context():
        category = Category(name="Rounding category")
        customer = Customer(phone="1234567890", name="Rounding Customer")
        db.session.add_all([category, customer])
        db.session.flush()
        item = MenuItem(
            name="Ten-rupee item",
            price=10,
            category_id=category.id,
            is_available=True,
            in_stock=True,
        )
        address = CustomerAddress(customer_id=customer.id, address_line="Rounding address")
        db.session.add_all([item, address])
        db.session.commit()
        customer_id, item_id, address_id = customer.id, item.id, address.id
        coupon = Coupon(code="HALF", discount_type="percent", value=5)
        assert coupon.compute_discount(10) == 1

    with client.session_transaction() as browser_session:
        browser_session["customer_id"] = customer_id
    response = client.post(
        "/api/checkout",
        json={
            "items": [{"item_id": item_id, "qty": 1}],
            "channel": "cod",
            "phone": "1234567890",
            "address_id": address_id,
        },
        headers={"Idempotency-Key": "test-rounding-checkout-key-001"},
    )
    assert response.status_code == 200
    assert response.get_json()["tax"] == 1
    assert response.get_json()["total"] == 51
    tracked = client.get("/api/orders/track/" + response.get_json()["order_number"])
    tracked_order = tracked.get_json()
    assert tracked_order["tax"] == 1
    assert tracked_order["total"] == 51
    assert "customer_phone" not in tracked_order
    assert "delivery_address" not in tracked_order
    assert "delivery_city" not in tracked_order
    assert "delivery_pincode" not in tracked_order
    assert "delivery_person_id" not in tracked_order
    assert "cod_collected" not in tracked_order
    assert "id" not in tracked_order


def test_api_mutations_reject_untrusted_origins(client):
    response = client.post(
        "/api/checkout",
        json={},
        headers={"Origin": "https://attacker.example"},
    )
    assert response.status_code == 403

    response = client.post("/api/checkout", json={}, environ_overrides={"HTTP_ORIGIN": ""})
    assert response.status_code == 403

    response = client.post("/api/checkout", json={})
    assert response.status_code == 400


@pytest.mark.parametrize(
    ("next_url", "expected_location"),
    [
        ("https://attacker.example", "/admin/"),
        ("//attacker.example", "/admin/"),
        ("/\\attacker.example", "/admin/"),
        ("/admin/orders", "/admin/orders"),
    ],
)
def test_admin_login_redirect_is_limited_to_safe_relative_urls(
    app, client, next_url, expected_location
):
    with app.app_context():
        admin = AdminUser(username="redirect-test-admin", role="super_admin")
        admin.set_password("redirect-test-password")
        db.session.add(admin)
        db.session.commit()

    response = client.post(
        "/admin/login",
        query_string={"next": next_url},
        data={"username": "redirect-test-admin", "password": "redirect-test-password"},
    )
    assert response.status_code == 302
    assert response.headers["Location"] == expected_location


def test_tracking_identifiers_have_more_entropy_and_lookup_is_rate_limited(app, client):
    with app.app_context():
        assert len(Order.generate_order_number()) == 20

    responses = [
        client.get("/api/orders/track/SP0000000000000000")
        for _ in range(31)
    ]
    assert all(response.status_code == 404 for response in responses[:30])
    assert responses[30].status_code == 429


def test_customer_password_signup_login_and_logout(app, client):
    signup = client.post(
        "/api/customer/signup",
        json={
            "phone": "123-456-7890",
            "name": "Password Customer",
            "password": "customer-password",
        },
    )
    assert signup.status_code == 200
    assert signup.get_json()["customer"]["phone"] == "1234567890"
    assert client.get("/api/customer/addresses").status_code == 200
    with app.app_context():
        customer = Customer.query.filter_by(phone="1234567890").one()
        assert customer.password_hash != "customer-password"
        assert customer.check_password("customer-password")

    client.post("/api/customer/logout")
    assert client.get("/api/customer/addresses").status_code == 401
    assert client.post(
        "/api/customer/login",
        json={"phone": "1234567890", "password": "wrong-password"},
    ).status_code == 401
    login = client.post(
        "/api/customer/login",
        json={"phone": "1234567890", "password": "customer-password"},
    )
    assert login.status_code == 200
    assert client.get("/api/customer/addresses").status_code == 200

    duplicate = client.post(
        "/api/customer/signup",
        json={
            "phone": "1234567890",
            "name": "Another Name",
            "password": "another-password",
        },
    )
    assert duplicate.status_code == 409


def test_legacy_customer_can_set_a_password_on_signup(app, client):
    with app.app_context():
        customer = Customer(phone="1234567890", name="Existing Customer")
        db.session.add(customer)
        db.session.commit()
        customer_id = customer.id

    signup = client.post(
        "/api/customer/signup",
        json={
            "phone": "1234567890",
            "name": "Replacement Name",
            "password": "new-customer-password",
        },
    )
    assert signup.status_code == 200
    assert signup.get_json()["customer"] == {
        "id": customer_id,
        "phone": "1234567890",
        "name": "Existing Customer",
    }
    with app.app_context():
        customer = db.session.get(Customer, customer_id)
        assert customer.check_password("new-customer-password")


def test_customer_password_auth_rejects_invalid_input_and_old_otp_routes(client):
    assert client.post(
        "/api/customer/signup",
        json={"phone": "1234567890", "name": "Customer", "password": "short"},
    ).status_code == 400
    assert client.post(
        "/api/customer/signup",
        json={"phone": "1234567890", "name": [], "password": "valid-password"},
    ).status_code == 400
    assert client.post(
        "/api/customer/login",
        json={"phone": "bad", "password": "valid-password"},
    ).status_code == 400
    assert client.post(
        "/api/customer/request-otp",
        json={"phone": "1234567890", "mode": "signup"},
    ).status_code == 404
    assert client.post(
        "/api/customer/verify-otp",
        json={"phone": "1234567890", "code": "123456"},
    ).status_code == 404


def test_customer_session_only_accesses_its_own_records(app, client):
    with app.app_context():
        customer = Customer(phone="1234567890", name="Session Customer")
        other_customer = Customer(phone="1234567891", name="Other Customer")
        db.session.add_all([customer, other_customer])
        db.session.flush()
        own_address = CustomerAddress(
            customer_id=customer.id,
            address_line="Own address",
        )
        other_address = CustomerAddress(
            customer_id=other_customer.id,
            address_line="Private address",
        )
        own_order = Order(
            order_number="SPSESSIONOWN000001",
            customer_id=customer.id,
        )
        other_order = Order(
            order_number="SPSESSIONOTHER00001",
            customer_id=other_customer.id,
        )
        db.session.add_all([own_address, other_address, own_order, other_order])
        db.session.commit()
        customer_id = customer.id
        own_address_id = own_address.id
        other_address_id = other_address.id

    with client.session_transaction() as browser_session:
        browser_session["customer_id"] = customer_id

    addresses = client.get("/api/customer/addresses").get_json()
    assert [address["id"] for address in addresses] == [own_address_id]
    assert client.delete(f"/api/customer/addresses/{other_address_id}").status_code == 404
    with app.app_context():
        assert db.session.get(CustomerAddress, other_address_id) is not None
    orders = client.get("/api/customer/orders").get_json()
    assert [order["order_number"] for order in orders] == ["SPSESSIONOWN000001"]


def test_online_checkout_creates_an_order_pending_admin_approval(app, client):
    with app.app_context():
        category = Category(name="Online category")
        customer = Customer(phone="1234567890", name="Online Customer")
        db.session.add_all([category, customer])
        db.session.flush()
        item = MenuItem(
            name="Online pastry",
            price=120,
            emoji="🥐",
            category_id=category.id,
            is_available=True,
            in_stock=True,
        )
        address = CustomerAddress(
            customer_id=customer.id,
            address_line="1 Payment Street",
            city="Test City",
            pincode="123456",
            is_default=True,
        )
        db.session.add_all([item, address])
        db.session.commit()
        customer_id, item_id, address_id = customer.id, item.id, address.id

    with client.session_transaction() as browser_session:
        browser_session["customer_id"] = customer_id

    response = client.post(
        "/api/checkout",
        json={
            "items": [{"item_id": item_id, "qty": 1}],
            "channel": "online",
            "phone": "1234567890",
            "address_id": address_id,
        },
        headers={"Idempotency-Key": "test-online-payment-request-001"},
    )
    assert response.status_code == 200
    assert response.get_json()["ok"] is True
    with app.app_context():
        order = Order.query.one()
        assert order.status == "pending"
        assert order.payment_status == "pending"


def test_razorpay_payment_is_verified_before_online_order_processing(app, client, monkeypatch):
    with app.app_context():
        admin = AdminUser(username="razorpay-admin", role="super_admin")
        admin.set_password("razorpay-admin-password")
        customer = Customer(phone="1234567890", name="Razorpay Customer")
        db.session.add_all([admin, customer])
        db.session.flush()
        order = create_order(status="pending", channel="online")
        order.customer_id = customer.id
        order_id, order_number, customer_id = order.id, order.order_number, customer.id
        db.session.commit()

    login = client.post(
        "/admin/login",
        data={"username": "razorpay-admin", "password": "razorpay-admin-password"},
    )
    assert login.status_code == 302
    assert client.post(
        f"/api/admin/orders/{order_id}/status",
        json={"status": "accepted"},
    ).status_code == 200
    assert client.post(
        f"/api/admin/orders/{order_id}/status",
        json={"status": "rejected"},
    ).status_code == 400

    with client.session_transaction() as browser_session:
        browser_session["customer_id"] = customer_id

    payment_reads = 0

    def fake_razorpay_request(method, path, payload=None):
        nonlocal payment_reads
        if method == "POST" and path == "/orders":
            assert payload["amount"] == 14500
            return {"id": "order_test123", "amount": 14500, "currency": "INR"}
        if method == "GET" and path == "/payments/pay_test123":
            payment_reads += 1
            return {
                "status": "authorized" if payment_reads == 1 else "captured",
                "order_id": "order_test123",
                "amount": 14500,
                "currency": "INR",
            }
        if method == "POST" and path == "/payments/pay_test123/capture":
            assert payload == {"amount": 14500, "currency": "INR"}
            return {"status": "captured"}
        raise AssertionError(f"Unexpected Razorpay request: {method} {path}")

    monkeypatch.setattr(api_module, "_razorpay_request", fake_razorpay_request)
    payment_order = client.post(
        "/api/checkout",
        json={"action": "create_payment", "order_number": order_number},
    )
    assert payment_order.status_code == 200
    assert payment_order.get_json()["razorpay_order_id"] == "order_test123"

    signature = hmac.new(
        b"test-razorpay-secret",
        b"order_test123|pay_test123",
        hashlib.sha256,
    ).hexdigest()
    invalid_signature = client.post(
        "/api/checkout",
        json={
            "action": "verify_payment",
            "order_number": order_number,
            "razorpay_order_id": "order_test123",
            "razorpay_payment_id": "pay_test123",
            "razorpay_signature": "0" * 64,
        },
    )
    assert invalid_signature.status_code == 400
    with app.app_context():
        assert db.session.get(Order, order_id).status == "accepted"

    verified = client.post(
        "/api/checkout",
        json={
            "action": "verify_payment",
            "order_number": order_number,
            "razorpay_order_id": "order_test123",
            "razorpay_payment_id": "pay_test123",
            "razorpay_signature": signature,
        },
    )
    assert verified.status_code == 200
    assert verified.get_json()["payment_status"] == "paid"
    assert client.post(
        "/api/checkout",
        json={
            "action": "verify_payment",
            "order_number": order_number,
            "razorpay_order_id": "order_test123",
            "razorpay_payment_id": "pay_test123",
            "razorpay_signature": signature,
        },
    ).get_json()["payment_status"] == "paid"
    with app.app_context():
        paid_order = db.session.get(Order, order_id)
        assert paid_order.status == "preparing"
        assert paid_order.payment_status == "paid"
        assert paid_order.razorpay_payment_id == "pay_test123"


def test_custom_cake_reference_image_validation_rejects_unsupported_and_oversized_data():
    assert api_module._validate_cake_reference_image(None) is None
    assert api_module._validate_cake_reference_image(
        "data:image/svg+xml;base64,PHN2Zy8+"
    ) is None
    assert api_module._validate_cake_reference_image(
        "data:image/png;base64," + ("A" * 2_800_001)
    ) is None


@pytest.mark.parametrize(
    ("payment_method", "expected_status"),
    [("cod", "preparing"), ("online", "accepted")],
)
def test_custom_cake_request_quote_and_customer_confirmation(
    app, client, monkeypatch, payment_method, expected_status
):
    with app.app_context():
        admin = AdminUser(username=f"cake-admin-{payment_method}", role="super_admin")
        admin.set_password("cake-admin-password")
        customer = Customer(phone="1234567890", name="Cake Customer")
        db.session.add_all([admin, customer])
        db.session.flush()
        address = CustomerAddress(
            customer_id=customer.id,
            address_line="42 Cake Street",
            city="Test City",
            pincode="123456",
            is_default=True,
        )
        db.session.add(address)
        db.session.commit()
        customer_id, address_id = customer.id, address.id

    with client.session_transaction() as browser_session:
        browser_session["customer_id"] = customer_id

    create_response = client.post(
        "/api/checkout",
        json={
            "action": "custom_cake_request",
            "description": "1 kg chocolate cake with pink flowers and Happy Birthday on top.",
            "reference_image": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l1sAAAAASUVORK5CYII=",
            "required_date": (datetime.utcnow() + timedelta(days=5)).date().isoformat(),
            "address_id": address_id,
            "payment_method": payment_method,
        },
        headers={"Idempotency-Key": f"cake-request-{payment_method}-key-001"},
    )
    assert create_response.status_code == 200
    order_number = create_response.get_json()["order_number"]
    duplicate = client.post(
        "/api/checkout",
        json={
            "action": "custom_cake_request",
            "description": "1 kg chocolate cake with pink flowers and Happy Birthday on top.",
            "reference_image": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l1sAAAAASUVORK5CYII=",
            "required_date": (datetime.utcnow() + timedelta(days=5)).date().isoformat(),
            "address_id": address_id,
            "payment_method": payment_method,
        },
        headers={"Idempotency-Key": f"cake-request-{payment_method}-key-001"},
    )
    assert duplicate.get_json()["order_number"] == order_number

    with app.app_context():
        order = Order.query.filter_by(order_number=order_number).one()
        order_id = order.id
        assert order.total == 0
        assert order.custom_cake_details
        assert "reference_image" in order.custom_cake_details

    assert client.post(
        "/admin/login",
        data={
            "username": f"cake-admin-{payment_method}",
            "password": "cake-admin-password",
        },
    ).status_code == 302
    quote_response = client.post(
        f"/api/admin/orders/{order_id}/status",
        json={"status": "accepted", "quote_total": 2500},
    )
    assert quote_response.status_code == 200
    with app.app_context():
        quoted_order = db.session.get(Order, order_id)
        assert quoted_order.status == "accepted"
        assert quoted_order.total == 2500
        assert quoted_order.items[0].price == 2500

    tracking = client.get(f"/api/orders/track/{order_number}").get_json()
    assert tracking["custom_cake_details"]["description"].startswith("1 kg chocolate cake")
    assert tracking["custom_cake_details"]["has_reference_image"] is True
    assert "reference_image" not in tracking["custom_cake_details"]
    tracking_with_image = client.get(
        f"/api/orders/track/{order_number}?include_reference_image=1"
    ).get_json()
    assert tracking_with_image["custom_cake_details"]["reference_image"].startswith(
        "data:image/png;base64,"
    )
    assert tracking["quote_confirmed"] is False
    admin_orders = client.get("/api/admin/orders").get_json()
    admin_order = next(order for order in admin_orders if order["id"] == order_id)
    assert admin_order["custom_cake_details"]["has_reference_image"] is True
    assert "reference_image" not in admin_order["custom_cake_details"]
    admin_orders_with_image = client.get(
        f"/api/admin/orders?reference_image_order_id={order_id}"
    ).get_json()
    admin_order_with_image = next(
        order for order in admin_orders_with_image if order["id"] == order_id
    )
    assert admin_order_with_image["custom_cake_details"]["reference_image"].startswith(
        "data:image/png;base64,"
    )

    with client.session_transaction() as browser_session:
        browser_session["customer_id"] = customer_id
    if payment_method == "online":
        monkeypatch.setattr(
            api_module,
            "_razorpay_request",
            lambda method, path, payload=None: {
                "id": "order_caketest",
                "amount": 250000,
                "currency": "INR",
            },
        )
        assert client.post(
            "/api/checkout",
            json={"action": "create_payment", "order_number": order_number},
        ).status_code == 409

    confirmed = client.post(
        "/api/checkout",
        json={"action": "confirm_cake_quote", "order_number": order_number},
    )
    assert confirmed.status_code == 200
    with app.app_context():
        accepted_order = db.session.get(Order, order_id)
        assert accepted_order.status == expected_status
        assert accepted_order.quote_confirmed is True
        if payment_method == "online":
            assert accepted_order.payment_status == "pending"


def test_unverified_online_orders_cannot_be_assigned_or_fulfilled(app, client):
    with app.app_context():
        admin = AdminUser(username="payment-test-admin", role="super_admin")
        admin.set_password("payment-test-password")
        person = DeliveryPerson(name="Payment Test Courier", active=True)
        person.set_password("payment-test-courier-password")
        db.session.add_all([admin, person])
        db.session.flush()
        pending_order = create_order(status="pending", channel="online")
        ready_order = create_order(
            person=person,
            status="ready",
            channel="online",
        )
        pending_order_id = pending_order.id
        ready_order_id = ready_order.id
        person_id = person.id

    login = client.post(
        "/admin/login",
        data={"username": "payment-test-admin", "password": "payment-test-password"},
    )
    assert login.status_code == 302
    assert client.post(
        f"/api/admin/orders/{pending_order_id}/status",
        json={"status": "preparing"},
    ).status_code == 409
    assert client.post(
        f"/api/delivery/orders/{pending_order_id}/assign",
        json={"delivery_person_id": person_id},
    ).status_code == 409

    courier_login = client.post(
        "/api/delivery/login",
        json={"name": "Payment Test Courier", "password": "payment-test-courier-password"},
    )
    assert courier_login.status_code == 200
    assert client.post(
        f"/api/delivery/orders/{ready_order_id}/deliver",
        json={},
    ).status_code == 409

    with app.app_context():
        assert db.session.get(Order, pending_order_id).status == "pending"
        assert db.session.get(Order, ready_order_id).status == "ready"


def test_whatsapp_channel_is_not_accepted_as_a_completed_order_flow(app, client):
    response = client.post(
        "/api/checkout",
        json={
            "items": [],
            "channel": "whatsapp",
            "phone": "1234567890",
            "address_id": 1,
        },
        headers={"Idempotency-Key": "test-whatsapp-flow-rejection-001"},
    )
    assert response.status_code == 503
    with app.app_context():
        assert Order.query.count() == 0


def test_legacy_whatsapp_orders_cannot_be_assigned_or_fulfilled(app, client):
    with app.app_context():
        admin = AdminUser(username="whatsapp-test-admin", role="super_admin")
        admin.set_password("whatsapp-test-password")
        person = DeliveryPerson(name="WhatsApp Test Courier", active=True)
        person.set_password("whatsapp-test-courier-password")
        db.session.add_all([admin, person])
        db.session.flush()
        pending_order = create_order(status="pending", channel="whatsapp")
        ready_order = create_order(
            person=person,
            status="ready",
            channel="whatsapp",
        )
        pending_order_id = pending_order.id
        ready_order_id = ready_order.id
        person_id = person.id

    client.post(
        "/admin/login",
        data={"username": "whatsapp-test-admin", "password": "whatsapp-test-password"},
    )
    assert client.post(
        f"/api/admin/orders/{pending_order_id}/status",
        json={"status": "preparing"},
    ).status_code == 409
    assert client.post(
        f"/api/delivery/orders/{pending_order_id}/assign",
        json={"delivery_person_id": person_id},
    ).status_code == 409

    client.post(
        "/api/delivery/login",
        json={"name": "WhatsApp Test Courier", "password": "whatsapp-test-courier-password"},
    )
    assert client.post(
        f"/api/delivery/orders/{ready_order_id}/deliver",
        json={},
    ).status_code == 409


def test_public_team_endpoint_returns_sorted_public_fields(app, client):
    with app.app_context():
        db.session.add_all([
            TeamMember(
                name="Second Member",
                role="Baker",
                avatar_emoji="🍞",
                sort_order=2,
            ),
            TeamMember(
                name="First Member",
                role="Chef",
                avatar_emoji="👩‍🍳",
                sort_order=1,
            ),
        ])
        db.session.commit()

    response = client.get("/api/team")
    assert response.status_code == 200
    assert response.get_json() == [
        {"name": "First Member", "role": "Chef", "avatar": "👩‍🍳", "photo": None},
        {"name": "Second Member", "role": "Baker", "avatar": "🍞", "photo": None},
    ]


def test_csp_allows_existing_inline_styles_without_relaxing_script_policy(client):
    response = client.get("/cart")
    policy = response.headers["Content-Security-Policy"]
    assert "style-src-attr 'unsafe-inline'" in policy
    script_policy = next(
        directive for directive in policy.split(";")
        if directive.strip().startswith("script-src ")
    )
    assert "'unsafe-inline'" not in script_policy


def test_tracking_csp_allows_razorpay_checkout_without_relaxing_other_pages(client):
    track = client.get("/track/SPTRACKINGTEST00001")
    track_policy = track.headers["Content-Security-Policy"]
    script_policy = next(
        directive for directive in track_policy.split(";")
        if directive.strip().startswith("script-src ")
    )
    assert "https://checkout.razorpay.com" in script_policy
    track_style_policy = next(
        directive for directive in track_policy.split(";")
        if directive.strip().startswith("style-src ")
    )
    assert "'unsafe-inline'" in track_style_policy
    assert "frame-src https://api.razorpay.com https://checkout.razorpay.com" in track_policy
    assert track.headers["Cross-Origin-Opener-Policy"] == "same-origin-allow-popups"

    cart_policy = client.get("/cart").headers["Content-Security-Policy"]
    assert "https://checkout.razorpay.com" not in cart_policy
    assert "'unsafe-inline'" not in next(
        directive for directive in cart_policy.split(";")
        if directive.strip().startswith("style-src ")
    )


def test_admin_coupon_rejects_malformed_expiry_dates(app, client):
    with app.app_context():
        admin = AdminUser(username="coupon-date-admin", role="super_admin")
        admin.set_password("coupon-date-password")
        db.session.add(admin)
        db.session.commit()

    assert client.post(
        "/admin/login",
        data={"username": "coupon-date-admin", "password": "coupon-date-password"},
    ).status_code == 302
    invalid = client.post(
        "/api/admin/coupons",
        json={"code": "BADDATE", "discount_type": "percent", "value": 10, "expires_at": "not-a-date"},
    )
    assert invalid.status_code == 400
    assert "YYYY-MM-DD" in invalid.get_json()["error"]

    invalid_type = client.post(
        "/api/admin/coupons",
        json={"code": "BADTYPE", "discount_type": "percent", "value": 10, "expires_at": []},
    )
    assert invalid_type.status_code == 400

    valid = client.post(
        "/api/admin/coupons",
        json={"code": "GOODDATE", "discount_type": "percent", "value": 10, "expires_at": "2030-01-01"},
    )
    assert valid.status_code == 201
    with app.app_context():
        assert Coupon.query.count() == 1


def test_site_content_database_errors_are_not_silently_replaced_with_defaults(
    app, client, monkeypatch
):
    def fail_content_lookup(_key, _default=""):
        raise RuntimeError("site content storage unavailable")

    monkeypatch.setattr(SiteContent, "get", staticmethod(fail_content_lookup))
    with pytest.raises(RuntimeError, match="site content storage unavailable"):
        client.get("/about")


def test_about_page_starts_with_non_mock_team_content(client):
    response = client.get("/about")
    assert response.status_code == 200
    assert b"Ravi Kumar" not in response.data


def test_checkout_atomically_decrements_finite_stock(app, client):
    with app.app_context():
        category = Category(name="Finite stock category")
        customer = Customer(phone="1234567890", name="Stock Customer")
        db.session.add_all([category, customer])
        db.session.flush()
        item = MenuItem(
            name="Two-stock pastry",
            price=100,
            category_id=category.id,
            is_available=True,
            in_stock=True,
            stock_quantity=2,
        )
        address = CustomerAddress(customer_id=customer.id, address_line="Stock address")
        db.session.add_all([item, address])
        db.session.commit()
        customer_id, item_id, address_id = customer.id, item.id, address.id

    with client.session_transaction() as browser_session:
        browser_session["customer_id"] = customer_id

    response = client.post(
        "/api/checkout",
        json={
            "items": [{"item_id": item_id, "qty": 2}],
            "channel": "cod",
            "phone": "1234567890",
            "address_id": address_id,
        },
        headers={"Idempotency-Key": "test-finite-stock-checkout-key-001"},
    )
    assert response.status_code == 200
    with app.app_context():
        item = db.session.get(MenuItem, item_id)
        assert item.stock_quantity == 0
        assert item.in_stock is False
        assert MenuItem.query.get(item_id).to_dict()["in_stock"] is False

    response = client.post(
        "/api/checkout",
        json={
            "items": [{"item_id": item_id, "qty": 1}],
            "channel": "cod",
            "phone": "1234567890",
            "address_id": address_id,
        },
        headers={"Idempotency-Key": "test-finite-stock-retry-key-0001"},
    )
    assert response.status_code == 400
    with app.app_context():
        assert Order.query.count() == 1


def test_admin_must_set_stock_for_new_menu_items(app, client):
    with app.app_context():
        admin = AdminUser(username="stock-admin", role="super_admin")
        admin.set_password("stock-admin-password")
        db.session.add(admin)
        db.session.commit()

    assert client.post(
        "/admin/login",
        data={"username": "stock-admin", "password": "stock-admin-password"},
    ).status_code == 302
    payload = {
        "name": "Stock-managed pastry",
        "price": 100,
        "category": "Stock management",
        "in_stock": True,
    }
    missing_stock = client.post("/api/admin/menu", json=payload)
    assert missing_stock.status_code == 400

    created = client.post(
        "/api/admin/menu",
        json={**payload, "stock_quantity": 3},
    )
    assert created.status_code == 201
    item = created.get_json()["item"]
    assert item["stock_quantity"] == 3
    updated = client.put(
        f"/api/admin/menu/{item['id']}",
        json={"stock_quantity": 0},
    )
    assert updated.status_code == 200
    assert updated.get_json()["item"]["in_stock"] is False
