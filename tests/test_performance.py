from sqlalchemy import event

from app.extensions import db
from app.models import AdminUser, Category, Customer, MenuItem, Order, SiteContent
from app import invalidate_site_content_cache


def test_public_pages_and_menu_api_avoid_repeated_queries(app, client):
    with app.app_context():
        db.session.add_all(
            SiteContent(key=key, value=key)
            for key in (
                "hero_eyebrow",
                "hero_title_line1",
                "hero_title_line2",
                "hero_title_em",
                "hero_sub",
                "stat_years",
                "stat_dishes",
                "stat_guests",
            )
        )
        for category_number in range(4):
            category = Category(name=f"Category {category_number}")
            db.session.add(category)
            db.session.flush()
            db.session.add(
                MenuItem(
                    name=f"Item {category_number}",
                    price=100,
                    category_id=category.id,
                    is_special=category_number == 0,
                )
            )
        db.session.commit()
        invalidate_site_content_cache()

        statements = []

        def capture_selects(
            _connection, _cursor, statement, _parameters, _context, _executemany
        ):
            if statement.lstrip().lower().startswith("select"):
                statements.append(statement)

        event.listen(db.engine, "before_cursor_execute", capture_selects)
        try:
            assert client.get("/home").status_code == 200
            assert len(statements) == 2

            statements.clear()
            assert client.get("/menu").status_code == 200
            assert statements == []

            response = client.get("/api/menu")
            assert response.status_code == 200
            assert len(statements) == 2
            assert len(response.get_json()) == 4
        finally:
            event.remove(db.engine, "before_cursor_execute", capture_selects)


def test_admin_orders_api_returns_bounded_pages(app, client):
    with app.app_context():
        admin = AdminUser(username="performance-admin", role="super_admin")
        admin.set_password("performance-admin-password")
        db.session.add(admin)
        db.session.add_all(
            Order(order_number=f"SPPAGE{number:014d}", status="pending")
            for number in range(51)
        )
        db.session.commit()

    login = client.post(
        "/admin/login",
        data={
            "username": "performance-admin",
            "password": "performance-admin-password",
        },
    )
    assert login.status_code == 302

    first_page = client.get("/api/admin/orders?page=1")
    second_page = client.get("/api/admin/orders?page=2")

    assert first_page.status_code == 200
    assert len(first_page.get_json()) == 50
    assert first_page.headers["X-Has-More"] == "true"
    assert len(second_page.get_json()) == 1
    assert second_page.headers["X-Has-More"] == "false"


def test_admin_menu_api_returns_bounded_pages(app, client):
    with app.app_context():
        admin = AdminUser(username="menu-performance-admin", role="super_admin")
        admin.set_password("menu-performance-admin-password")
        category = Category(name="Paged category")
        db.session.add_all([admin, category])
        db.session.flush()
        db.session.add_all(
            MenuItem(
                name=f"Paged item {number}",
                price=100,
                category_id=category.id,
            )
            for number in range(51)
        )
        db.session.commit()

    login = client.post(
        "/admin/login",
        data={
            "username": "menu-performance-admin",
            "password": "menu-performance-admin-password",
        },
    )
    assert login.status_code == 302

    first_page = client.get("/api/admin/menu?page=1")
    second_page = client.get("/api/admin/menu?page=2")

    assert first_page.status_code == 200
    assert len(first_page.get_json()) == 50
    assert first_page.headers["X-Has-More"] == "true"
    assert len(second_page.get_json()) == 1
    assert second_page.headers["X-Has-More"] == "false"


def test_customer_order_history_api_returns_bounded_pages(app, client):
    with app.app_context():
        customer = Customer(phone="9876543210", name="Paged customer")
        db.session.add(customer)
        db.session.flush()
        db.session.add_all(
            Order(
                order_number=f"SPCUS{number:015d}",
                customer_id=customer.id,
                status="pending",
            )
            for number in range(26)
        )
        db.session.commit()
        customer_id = customer.id

    with client.session_transaction() as browser_session:
        browser_session["customer_id"] = customer_id

    first_page = client.get("/api/customer/orders?page=1")
    second_page = client.get("/api/customer/orders?page=2")

    assert first_page.status_code == 200
    assert len(first_page.get_json()) == 25
    assert first_page.headers["X-Has-More"] == "true"
    assert len(second_page.get_json()) == 1
    assert second_page.headers["X-Has-More"] == "false"


def test_admin_content_edit_invalidates_public_content_cache(app, client):
    with app.app_context():
        admin = AdminUser(username="content-admin", role="super_admin")
        admin.set_password("content-admin-password")
        db.session.add_all(
            [
                admin,
                SiteContent(key="hero_title_line1", value="Old title"),
            ]
        )
        db.session.commit()
        invalidate_site_content_cache()

    assert b"Old title" in client.get("/home").data
    client.post(
        "/admin/login",
        data={"username": "content-admin", "password": "content-admin-password"},
    )

    updated = client.post(
        "/api/admin/content",
        json={"hero_title_line1": "New title"},
    )
    assert updated.status_code == 200
    assert b"New title" in client.get("/home").data
