def test_customer_login_is_restored_from_session_and_logout_clears_it(app, client):
    app.config["CUSTOMER_OTP_DEBUG"] = True

    requested = client.post(
        "/api/customer/request-otp",
        json={"phone": "1234567890", "name": "Session Customer", "mode": "signup"},
    )
    assert requested.status_code == 200

    verified = client.post(
        "/api/customer/verify-otp",
        json={"phone": "1234567890", "code": requested.get_json()["debug_code"]},
    )
    assert verified.status_code == 200
    with client.session_transaction() as browser_session:
        assert browser_session.permanent
        assert browser_session["customer_id"] == verified.get_json()["customer"]["id"]

    restored = client.get("/api/customer/me")
    assert restored.status_code == 200
    assert restored.get_json() == {
        "ok": True,
        "authenticated": True,
        "customer": verified.get_json()["customer"],
    }

    assert client.post("/api/customer/logout").get_json() == {"ok": True}
    assert client.get("/api/customer/me").get_json() == {
        "ok": True,
        "authenticated": False,
    }
    assert client.get("/api/customer/addresses").status_code == 401
