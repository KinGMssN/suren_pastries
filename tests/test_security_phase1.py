from datetime import datetime, timedelta
import secrets

import pytest

from app.extensions import db
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
    TeamMember,
)


def create_order(person=None, status="ready", channel="cod"):
    order = Order(
        order_number="SPTEST" + secrets.token_hex(4).upper(),
        customer_name="Test Customer",
        customer_phone="1234567890",
        channel=channel,
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
    response = client.post(
        f"/api/delivery/orders/{order_id}/assign",
        json={"delivery_person_id": person_id},
    )
    assert response.status_code == 200

    mark_ready = client.post(
        f"/api/admin/orders/{order_id}/status",
        json={"status": "ready"},
    )
    assert mark_ready.status_code == 200
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


def test_customer_otp_signup_login_and_logout(app, client):
    app.config["CUSTOMER_OTP_DEBUG"] = True
    requested = client.post(
        "/api/customer/request-otp",
        json={"phone": "1234567890", "name": "OTP Customer", "mode": "signup"},
    )
    assert requested.status_code == 200
    signup_code = requested.get_json()["debug_code"]
    assert len(signup_code) == 6

    with app.app_context():
        customer = Customer.query.filter_by(phone="1234567890").one()
        customer_id = customer.id
        assert customer.otp_hash != signup_code
        assert customer.otp_attempts == 0

    verified = client.post(
        "/api/customer/verify-otp",
        json={"phone": "1234567890", "code": signup_code},
    )
    assert verified.status_code == 200
    assert verified.get_json()["customer"] == {
        "id": customer_id,
        "phone": "1234567890",
        "name": "OTP Customer",
    }
    assert client.get("/api/customer/addresses").status_code == 200

    assert client.post("/api/customer/logout").get_json()["ok"] is True
    assert client.get("/api/customer/addresses").status_code == 401

    requested = client.post(
        "/api/customer/request-otp",
        json={"phone": "1234567890", "mode": "login"},
    )
    assert requested.status_code == 200
    login_code = requested.get_json()["debug_code"]
    assert client.post(
        "/api/customer/verify-otp",
        json={"phone": "1234567890", "code": login_code},
    ).status_code == 200


def test_customer_otp_requires_a_delivery_provider_outside_debug_mode(app, client):
    app.config["CUSTOMER_OTP_DEBUG"] = False
    response = client.post(
        "/api/customer/request-otp",
        json={"phone": "1234567890", "name": "Pending Customer", "mode": "signup"},
    )
    assert response.status_code == 503
    assert response.get_json()["ok"] is False
    with app.app_context():
        assert Customer.query.filter_by(phone="1234567890").first() is None


def test_customer_login_without_an_account_sends_user_to_signup(client):
    response = client.post(
        "/api/customer/request-otp",
        json={"phone": "1234567890", "mode": "login"},
    )
    assert response.status_code == 404
    assert response.get_json()["needs_name"] is True


def test_customer_otp_rejects_malformed_request_payload(client):
    response = client.post(
        "/api/customer/request-otp",
        json={"phone": "1234567890", "mode": []},
    )
    assert response.status_code == 400


def test_customer_otp_attempts_are_limited_and_codes_expire(app, client):
    app.config["CUSTOMER_OTP_DEBUG"] = True
    requested = client.post(
        "/api/customer/request-otp",
        json={"phone": "1234567890", "name": "Limited Customer", "mode": "signup"},
    )
    assert requested.status_code == 200

    wrong_code = "000000" if requested.get_json()["debug_code"] != "000000" else "000001"
    for _ in range(5):
        response = client.post(
            "/api/customer/verify-otp",
            json={"phone": "1234567890", "code": wrong_code},
        )
    assert response.status_code == 400
    blocked = client.post(
        "/api/customer/verify-otp",
        json={"phone": "1234567890", "code": requested.get_json()["debug_code"]},
    )
    assert blocked.status_code == 429

    with app.app_context():
        customer = Customer.query.filter_by(phone="1234567890").one()
        customer.otp_expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.session.commit()
        customer.otp_attempts = 0
        db.session.commit()
    expired = client.post(
        "/api/customer/verify-otp",
        json={"phone": "1234567890", "code": requested.get_json()["debug_code"]},
    )
    assert expired.status_code == 400


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


def test_online_checkout_is_rejected_without_a_payment_provider(app, client):
    response = client.post(
        "/api/checkout",
        json={
            "items": [],
            "channel": "online",
            "phone": "1234567890",
            "address_id": 1,
        },
        headers={"Idempotency-Key": "test-online-payment-rejection-001"},
    )
    assert response.status_code == 503
    assert response.get_json()["ok"] is False
    with app.app_context():
        assert Order.query.count() == 0


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


def test_about_page_starts_with_non_mock_team_content(client):
    response = client.get("/about")
    assert response.status_code == 200
    assert b"Ravi Kumar" not in response.data
