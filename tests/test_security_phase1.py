import secrets

from app.extensions import db
from app.models import AdminUser, DeliveryPerson, Order, OrderItem


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
