def test_customer_login_is_restored_from_session_and_logout_clears_it(app, client):
    signup = client.post(
        "/api/customer/signup",
        json={
            "phone": "1234567890",
            "name": "Session Customer",
            "password": "customer-password",
        },
    )
    assert signup.status_code == 200
    with client.session_transaction() as browser_session:
        assert browser_session.permanent
        assert browser_session["customer_id"] == signup.get_json()["customer"]["id"]

    restored = client.get("/api/customer/me")
    assert restored.status_code == 200
    assert restored.get_json() == {
        "ok": True,
        "authenticated": True,
        "customer": signup.get_json()["customer"],
    }

    assert client.post("/api/customer/logout").get_json() == {"ok": True}
    assert client.get("/api/customer/me").get_json() == {
        "ok": True,
        "authenticated": False,
    }
    assert client.get("/api/customer/addresses").status_code == 401

    logged_in = client.post(
        "/api/customer/login",
        json={"phone": "1234567890", "password": "customer-password"},
    )
    assert logged_in.status_code == 200
    assert client.get("/api/customer/addresses").status_code == 200
