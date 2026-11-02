from xml.etree import ElementTree

from app.extensions import db
from app.models import SiteContent


def test_public_pages_get_descriptions_and_configured_canonical_urls(app, client):
    app.config["PUBLIC_SITE_URL"] = "https://shop.example"
    response = client.get("/menu")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert '<meta name="description" content="Browse the Suren Pastries menu' in html
    assert '<link rel="canonical" href="https://shop.example/menu"/>' in html

    account = client.get("/account").get_data(as_text=True)
    assert '<link rel="canonical"' not in account


def test_robots_and_sitemap_use_only_configured_public_origin(app, client):
    app.config["PUBLIC_SITE_URL"] = "https://shop.example"
    robots = client.get("/robots.txt")
    assert robots.status_code == 200
    assert "Disallow: /account" in robots.get_data(as_text=True)
    assert "Sitemap: https://shop.example/sitemap.xml" in robots.get_data(as_text=True)

    sitemap = client.get("/sitemap.xml")
    assert sitemap.status_code == 200
    root = ElementTree.fromstring(sitemap.data)
    namespace = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    locations = [
        node.text
        for node in root.findall("s:url/s:loc", namespace)
    ]
    assert "https://shop.example/menu" in locations
    assert "https://shop.example/customized-cake" in locations
    assert all(location.startswith("https://shop.example/") for location in locations)
    assert not any(
        path in location
        for location in locations
        for path in ("/account", "/cart", "/delivery", "/track/")
    )


def test_sitemap_does_not_guess_deployment_domain(app, client):
    app.config["PUBLIC_SITE_URL"] = ""
    response = client.get("/sitemap.xml")
    assert response.status_code == 503
    assert b"Set PUBLIC_SITE_URL" in response.data
    assert "Sitemap:" not in client.get("/robots.txt").get_data(as_text=True)


def test_customized_cake_page_uses_configured_contact_and_has_customization_flow(app, client):
    app.config["PUBLIC_SITE_URL"] = "https://shop.example"
    SiteContent.set("whatsapp", "+91 90327 17635")
    db.session.commit()

    response = client.get("/customized-cake")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert '<link rel="canonical" href="https://shop.example/customized-cake"/>' in html
    assert 'aria-current="page">Customized Cake</a>' in html
    assert "Design Your" in html and "Dream Cake" in html
    assert "Have a Design in Mind?" in html
    assert "Your Cake Summary" in html
    assert "Final Price" in html
    assert "To Be Confirmed by the Bakery" in html
    assert "https://wa.me/919032717635?" in html
    assert "Hi%21%20I%20would%20like%20to%20discuss%20a%20customized%20cake%20order." in html
    assert client.post("/customized-cake", data={}).status_code == 405


def test_customized_cake_does_not_guess_a_whatsapp_number(app, client):
    response = client.get("/customized-cake")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "WhatsApp enquiries are unavailable" in html
    assert "https://wa.me/" not in html
