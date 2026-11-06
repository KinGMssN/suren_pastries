from app.extensions import db
from app.models import AdminUser, Customer, CustomerAddress, DeletedRecord, Order


def test_customer_deletion_retains_only_name_and_phone_and_anonymizes_orders(app, client):
    with app.app_context():
        customer = Customer(
            phone="1234567890",
            name="Retention Test",
            password_hash="customer-password-hash",
            otp_hash="one-time-secret-hash",
        )
        db.session.add(customer)
        db.session.flush()
        address = CustomerAddress(
            customer_id=customer.id,
            address_line="1 Private Street",
            city="Private City",
            pincode="123456",
        )
        order = Order(
            order_number="SPRETENTIONTEST",
            customer_id=customer.id,
            customer_name=customer.name,
            customer_phone=customer.phone,
            delivery_address=address.address_line,
            delivery_city=address.city,
            delivery_pincode=address.pincode,
        )
        db.session.add_all([address, order])
        db.session.commit()
        customer_id = customer.id
        order_id = order.id

    with client.session_transaction() as browser_session:
        browser_session["customer_id"] = customer_id

    response = client.delete("/api/customer/account")
    assert response.status_code == 200

    with app.app_context():
        assert db.session.get(Customer, customer_id) is None
        assert CustomerAddress.query.count() == 0
        archived_customer = DeletedRecord.query.filter_by(table_name="customers").one()
        assert archived_customer.record_data == {
            "name": "Retention Test",
            "phone": "1234567890",
        }
        assert DeletedRecord.query.filter_by(table_name="customer_addresses").count() == 0

        retained_order = db.session.get(Order, order_id)
        assert retained_order is not None
        assert retained_order.customer_id is None
        assert retained_order.customer_name == "Deleted customer"
        assert retained_order.customer_phone == ""
        assert retained_order.delivery_address == ""
        assert retained_order.delivery_city == ""
        assert retained_order.delivery_pincode == ""


def test_only_super_admin_can_view_and_purge_archived_records(app, client):
    with app.app_context():
        menu_admin = AdminUser(username="retention-menu-admin", role="menu_admin")
        menu_admin.set_password("retention-menu-password")
        super_admin = AdminUser(username="retention-super-admin", role="super_admin")
        super_admin.set_password("retention-super-password")
        archived = DeletedRecord(
            table_name="customers",
            original_id=37,
            record_data={
                "name": "Archived Name",
                "phone": "1234567890",
                "otp_hash": "must-not-be-returned",
            },
        )
        db.session.add_all([menu_admin, super_admin, archived])
        db.session.commit()
        archived_id = archived.id

    client.post(
        "/admin/login",
        data={"username": "retention-menu-admin", "password": "retention-menu-password"},
    )
    menu_dashboard = client.get("/admin/")
    assert menu_dashboard.status_code == 200
    assert b"Deleted records" not in menu_dashboard.data
    assert client.get("/api/admin/deleted-records").status_code == 403
    assert client.delete(f"/api/admin/deleted-records/{archived_id}").status_code == 403

    client.get("/admin/logout")
    client.post(
        "/admin/login",
        data={"username": "retention-super-admin", "password": "retention-super-password"},
    )
    super_dashboard = client.get("/admin/")
    assert super_dashboard.status_code == 200
    assert b"Deleted records" in super_dashboard.data
    response = client.get("/api/admin/deleted-records")
    assert response.status_code == 200
    assert response.get_json() == [
        {
            "id": archived_id,
            "table": "customers",
            "original_id": 37,
            "data": {"name": "Archived Name", "phone": "1234567890"},
            "deleted_by": None,
            "deleted_at": response.get_json()[0]["deleted_at"],
        }
    ]

    purged = client.delete(f"/api/admin/deleted-records/{archived_id}")
    assert purged.status_code == 200
    assert client.get("/api/admin/deleted-records").get_json() == []
