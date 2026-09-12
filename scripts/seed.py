import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models import AdminUser, Category, Coupon, MenuItem, SiteContent, TeamMember
from sqlalchemy import text

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
        db.session.execute(text(
            "ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS role VARCHAR(30) NOT NULL DEFAULT 'super_admin'"
        ))
        db.session.commit()

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
            user.role = "super_admin"
            print(f"Admin user '{username}' already existed — password reset from .env.")

        subadmin_username = app.config.get("SUBADMIN_USERNAME")
        subadmin_password = app.config.get("SUBADMIN_PASSWORD")
        if subadmin_username and subadmin_password:
            subadmin = AdminUser.query.filter_by(username=subadmin_username).first()
            if subadmin is None:
                subadmin = AdminUser(username=subadmin_username, role="menu_admin")
                db.session.add(subadmin)
                print(f"Created menu sub-admin '{subadmin_username}'.")
            subadmin.set_password(subadmin_password)
            subadmin.role = "menu_admin"

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
