import secrets

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
    assert tracked.get_json()["tax"] == 1
