"""
Run this once after your PostgreSQL database exists and .env is configured:

    python scripts/seed.py

It will:
  1. Create all tables (safe to re-run — it won't drop existing data)
  2. Create the admin login (from ADMIN_USERNAME / ADMIN_PASSWORD in .env),
     or update the password if that username already exists
  3. Seed the menu with the same 30 dishes from the original static site,
     but only if the menu_items table is currently empty
  4. Seed two starter coupons (SUREN20, FLAT50) so the cart's promo code
     box has something to test, only if the coupons table is empty
  5. Seed the default site content used on the landing/about pages, only
     if that key doesn't already exist
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models import AdminUser, Category, Coupon, MenuItem, SiteContent, TeamMember

MENU_DATA = {
    "Starters": [
        dict(name="Paneer Tikka", description="Chargrilled cottage cheese with spiced marinade and mint chutney", price=180, emoji="🍢", tag="Popular", is_special=True),
        dict(name="Veg Spring Rolls", description="Crispy golden rolls with seasoned vegetable filling", price=120, emoji="🥢", tag=""),
        dict(name="Chicken 65", description="Spicy deep-fried chicken bites, South Indian style", price=220, emoji="🍗", tag="Spicy"),
        dict(name="Gobi Manchurian", description="Crispy cauliflower in Indo-Chinese sauce", price=150, emoji="🥦", tag=""),
        dict(name="Samosa Chaat", description="Flaky samosas topped with tangy chutneys and yogurt", price=110, emoji="🫕", tag=""),
        dict(name="Fish Fry", description="Coastal style marinated fish, pan seared", price=260, emoji="🐟", tag="Special"),
    ],
    "Mains": [
        dict(name="Butter Chicken", description="Rich tomato-cream gravy with tender chicken pieces", price=280, emoji="🍛", tag="Bestseller", is_special=True),
        dict(name="Dal Makhani", description="Slow-cooked black lentils in buttery tomato sauce", price=200, emoji="🫘", tag=""),
        dict(name="Biryani Dum", description="Fragrant basmati rice layered with whole spices", price=320, emoji="🍚", tag="Popular", is_special=True),
        dict(name="Palak Paneer", description="Creamed spinach with soft cottage cheese cubes", price=240, emoji="🥬", tag=""),
        dict(name="Chicken Curry", description="Traditional South Indian style coconut curry", price=270, emoji="🍲", tag=""),
        dict(name="Mutton Rogan Josh", description="Slow-braised mutton in Kashmiri aromatic sauce", price=380, emoji="🥘", tag="Chef's pick", is_special=True),
        dict(name="Chole Bhature", description="Spiced chickpeas with deep-fried fluffy bread", price=180, emoji="🫕", tag=""),
        dict(name="Mixed Veg Curry", description="Seasonal vegetables in rustic masala gravy", price=190, emoji="🥗", tag=""),
    ],
    "Breads": [
        dict(name="Butter Naan", description="Leavened flatbread from the tandoor, brushed with butter", price=50, emoji="🫓", tag=""),
        dict(name="Garlic Roti", description="Whole wheat with roasted garlic butter", price=55, emoji="🫓", tag=""),
        dict(name="Paratha Basket", description="Assorted stuffed parathas, served 3 per basket", price=140, emoji="🥙", tag=""),
        dict(name="Puri", description="Puffed deep-fried wheat bread, 3 pieces", price=60, emoji="🫓", tag=""),
        dict(name="Lachha Paratha", description="Multi-layered flaky whole wheat flatbread", price=70, emoji="🫓", tag=""),
    ],
    "Desserts": [
        dict(name="Gulab Jamun", description="Soft milk-solid dumplings soaked in rose syrup", price=90, emoji="🍮", tag="Classic"),
        dict(name="Kulfi Falooda", description="Indian ice cream with vermicelli and rose syrup", price=130, emoji="🍨", tag="Special", is_special=True),
        dict(name="Rasgulla", description="Spongy cottage cheese balls in light sugar syrup", price=95, emoji="🍡", tag=""),
        dict(name="Kheer", description="Slow-cooked rice pudding with cardamom and nuts", price=100, emoji="🍚", tag=""),
        dict(name="Halwa", description="Semolina pudding with ghee, nuts and saffron", price=110, emoji="🟡", tag=""),
    ],
    "Drinks": [
        dict(name="Mango Lassi", description="Thick yogurt blended with Alphonso mango pulp", price=95, emoji="🥭", tag=""),
        dict(name="Masala Chai", description="Spiced milk tea, freshly brewed to perfection", price=45, emoji="☕", tag=""),
        dict(name="Fresh Lime Soda", description="Sweet or salted, your choice, chilled", price=60, emoji="🍋", tag=""),
        dict(name="Buttermilk", description="Tempered with mustard, curry leaf and ginger", price=50, emoji="🥛", tag=""),
        dict(name="Rose Sharbat", description="Chilled rose drink with basil seeds", price=70, emoji="🌹", tag=""),
        dict(name="Fresh Juice", description="Seasonal fruit — ask server for today's options", price=80, emoji="🧃", tag=""),
    ],
}

TEAM_DATA = [
    dict(name="Ravi Kumar", role="Head Chef & Founder", avatar_emoji="👨‍🍳"),
    dict(name="Lakshmi Devi", role="Executive Chef", avatar_emoji="👩‍🍳"),
    dict(name="Arjun Rao", role="Restaurant Manager", avatar_emoji="👨‍💼"),
    dict(name="Priya Sharma", role="Customer Experience", avatar_emoji="👩‍💼"),
]

DEFAULT_CONTENT = {
    "phone_display": "090327 17635",
    "phone": "09032717635",
    "whatsapp": "919032717635",
    "email": "hello@surenpastries.in",
    "address_short": "Kurmannapalem, Gajuwaka",
    "address_full": "Kurmannapalem, Gajuwaka,<br>Andhra Pradesh 530046",
    "hero_eyebrow": "Est. 2008 · Vizianagaram",
    "hero_title_line1": "Where every",
    "hero_title_line2": "meal is an",
    "hero_title_em": "experience",
    "hero_sub": "Handcrafted dishes rooted in South Indian tradition, served with modern elegance. Fresh ingredients, soulful recipes.",
    "stat_years": "15+",
    "stat_dishes": "80+",
    "stat_guests": "50k+",
}


def run():
    app = create_app()
    with app.app_context():
        db.create_all()

        # 1. Admin user
        username = app.config["ADMIN_USERNAME"]
        password = app.config["ADMIN_PASSWORD"]
        user = AdminUser.query.filter_by(username=username).first()
        if user is None:
            user = AdminUser(username=username)
            user.set_password(password)
            db.session.add(user)
            print(f"Created admin user '{username}'.")
        else:
            user.set_password(password)
            print(f"Admin user '{username}' already existed — password reset from .env.")

        # 2. Menu + categories
        if MenuItem.query.count() == 0:
            for order, (cat_name, items) in enumerate(MENU_DATA.items()):
                category = Category(name=cat_name, sort_order=order)
                db.session.add(category)
                db.session.flush()
                for item in items:
                    db.session.add(MenuItem(category_id=category.id, is_available=True, **item))
            print(f"Seeded {sum(len(v) for v in MENU_DATA.values())} menu items across {len(MENU_DATA)} categories.")
        else:
            print("Menu already has items — skipped menu seeding.")

        # 3. Coupons
        if Coupon.query.count() == 0:
            db.session.add(Coupon(code="SUREN20", description="20% off your order", discount_type="percent", value=20, active=True))
            db.session.add(Coupon(code="FLAT50", description="₹50 off your order", discount_type="flat", value=50, active=True))
            print("Seeded starter coupons SUREN20 and FLAT50.")
        else:
            print("Coupons already exist — skipped coupon seeding.")

        # 3b. Team members
        if TeamMember.query.count() == 0:
            for order, member in enumerate(TEAM_DATA):
                db.session.add(TeamMember(sort_order=order, **member))
            print(f"Seeded {len(TEAM_DATA)} team members.")
        else:
            print("Team members already exist — skipped team seeding.")

        # 4. Site content
        for key, value in DEFAULT_CONTENT.items():
            if SiteContent.query.get(key) is None:
                db.session.add(SiteContent(key=key, value=value))
        print("Ensured default site content is present.")

        db.session.commit()
        print("\nDone. Start the server with:  flask --app wsgi run  (or python wsgi.py)")


if __name__ == "__main__":
    run()
