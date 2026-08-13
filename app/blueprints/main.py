from flask import Blueprint, render_template

from app.models import Category, MenuItem

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def index():
    """Animated splash/loader screen, then redirects to /home via JS."""
    return render_template("index.html")


@main_bp.route("/home")
def home():
    # A handful of "chef's specials" for the landing page preview strip.
    specials = (
        MenuItem.query.filter(MenuItem.tag != "", MenuItem.is_available.is_(True))
        .order_by(MenuItem.id)
        .limit(4)
        .all()
    )
    return render_template("landing.html", specials=specials)


@main_bp.route("/menu")
def menu():
    categories = Category.query.order_by(Category.sort_order, Category.name).all()
    return render_template("menu.html", categories=categories)


@main_bp.route("/about")
def about():
    return render_template("details.html")


@main_bp.route("/cart")
def cart():
    return render_template("cart.html")
