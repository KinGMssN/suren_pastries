from xml.etree import ElementTree

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


def test_customized_cake_page_has_customization_flow_without_whatsapp_redirect(app, client):
    app.config["PUBLIC_SITE_URL"] = "https://shop.example"

    response = client.get("/customized-cake")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert '<link rel="canonical" href="https://shop.example/customized-cake"/>' in html
    assert 'aria-current="page">Custom Cakes</a>' in html
    assert "Made" in html
    assert "For example:" not in html
    assert "Include the size, flavour" not in html
    assert 'name="description"' in html
    assert 'type="file" accept="image/jpeg,image/png,image/webp"' in html
    assert 'type="checkbox" checked' in html
    assert 'name="flavour"' not in html
    assert 'name="size"' not in html
    assert "Send cake request" in html
    assert "customized-cake.js" in html
    csp = response.headers["Content-Security-Policy"]
    assert "img-src 'self' data: https://images.unsplash.com" in csp
    assert "https://wa.me/" not in html
    assert client.post("/customized-cake", data={}).status_code == 405
