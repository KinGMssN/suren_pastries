from xml.sax.saxutils import escape

from flask import Blueprint, Response, current_app, render_template

from app.models import Category, MenuItem

main_bp = Blueprint("main", __name__)

SITEMAP_PATHS = (
    "/home",
    "/menu",
    "/customized-cake",
    "/about",
    "/privacy",
    "/refund-policy",
    "/terms",
    "/cookies",
)


@main_bp.route("/")
def index():
    """Animated splash/loader screen, then redirects to /home via JS."""
    return render_template("index.html")


@main_bp.route("/home")
def home():
    specials = (
        MenuItem.query.filter(MenuItem.is_special.is_(True), MenuItem.is_available.is_(True))
        .order_by(MenuItem.id)
        .limit(8)
        .all()
    )
    return render_template("landing.html", specials=specials)


@main_bp.route("/menu")
def menu():
    categories = Category.query.order_by(Category.sort_order, Category.name).all()
    return render_template("menu.html", categories=categories)


@main_bp.route("/customized-cake")
def customized_cake():
    return render_template("customized_cake.html")


@main_bp.route("/about")
def about():
    return render_template("details.html")


@main_bp.route("/privacy")
def privacy():
    return render_template("policy.html", policy="privacy")


@main_bp.route("/refund-policy")
def refund_policy():
    return render_template("policy.html", policy="refund")


@main_bp.route("/terms")
def terms():
    return render_template("policy.html", policy="terms")


@main_bp.route("/cookies")
def cookies():
    return render_template("policy.html", policy="cookies")


@main_bp.route("/cart")
def cart():
    return render_template("cart.html")


@main_bp.route("/login")
def login():
    return render_template("login.html")


@main_bp.route("/signup")
def signup():
    return render_template("signup.html")


@main_bp.route("/account")
def account():
    return render_template("account.html")


@main_bp.route("/delivery")
def delivery():
    return render_template("delivery.html")


@main_bp.route("/track/<order_number>")
def track(order_number):
    return render_template("track.html", order_number=order_number)


@main_bp.route("/delivery/order/<int:order_id>")
def delivery_order(order_id):
    return render_template("delivery_order.html", order_id=order_id)


@main_bp.route("/robots.txt")
def robots_txt():
    lines = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /account",
        "Disallow: /cart",
        "Disallow: /delivery",
        "Disallow: /delivery/order/",
        "Disallow: /login",
        "Disallow: /signup",
        "Disallow: /track/",
    ]
    public_site_url = current_app.config.get("PUBLIC_SITE_URL", "")
    if public_site_url:
        lines.append(f"Sitemap: {public_site_url}/sitemap.xml")
    return Response("\n".join(lines) + "\n", mimetype="text/plain")


@main_bp.route("/sitemap.xml")
def sitemap_xml():
    public_site_url = current_app.config.get("PUBLIC_SITE_URL", "")
    if not public_site_url:
        return Response(
            "Set PUBLIC_SITE_URL to enable the sitemap.\n",
            status=503,
            mimetype="text/plain",
        )
    locations = "".join(
        f"<url><loc>{escape(public_site_url + path)}</loc></url>"
        for path in SITEMAP_PATHS
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{locations}</urlset>"
    )
    return Response(xml, mimetype="application/xml")