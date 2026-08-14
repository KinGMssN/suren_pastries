import secrets
from datetime import datetime

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db


class AdminUser(UserMixin, db.Model):
    __tablename__ = "admin_users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, raw_password: str) -> None:
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password: str) -> bool:
        return check_password_hash(self.password_hash, raw_password)


class Category(db.Model):
    __tablename__ = "categories"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    sort_order = db.Column(db.Integer, default=0)

    items = db.relationship(
        "MenuItem", backref="category", lazy=True, cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Category {self.name}>"


class MenuItem(db.Model):
    __tablename__ = "menu_items"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(300), default="")
    price = db.Column(db.Integer, nullable=False)  # stored in rupees, whole numbers
    emoji = db.Column(db.String(10), default="🍽️")
    tag = db.Column(db.String(40), default="")
    is_available = db.Column(db.Boolean, default=True, nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "desc": self.description,
            "price": self.price,
            "emoji": self.emoji,
            "tag": self.tag or None,
            "category": self.category.name if self.category else None,
            "is_available": self.is_available,
        }

class TeamMember(db.Model):
    __tablename__ = "team_members"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(120), default="")
    avatar_emoji = db.Column(db.String(10), default="👤")
    photo_data = db.Column(db.Text, nullable=True)  # base64 data URI, overrides avatar_emoji when set
    sort_order = db.Column(db.Integer, default=0)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "role": self.role,
            "avatar": self.avatar_emoji,
            "photo": self.photo_data or None,
        }


class Coupon(db.Model):
    __tablename__ = "coupons"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(30), unique=True, nullable=False)
    description = db.Column(db.String(200), default="")
    discount_type = db.Column(db.String(10), default="percent")  # percent | flat
    value = db.Column(db.Integer, nullable=False)  # % or rupees, depending on type
    max_uses = db.Column(db.Integer, nullable=True)  # None = unlimited
    uses = db.Column(db.Integer, default=0)
    expires_at = db.Column(db.DateTime, nullable=True)
    active = db.Column(db.Boolean, default=True)

    def is_valid(self):
        if not self.active:
            return False
        if self.expires_at and self.expires_at < datetime.utcnow():
            return False
        if self.max_uses is not None and self.uses >= self.max_uses:
            return False
        return True

    def compute_discount(self, subtotal: int) -> int:
        if self.discount_type == "percent":
            return round(subtotal * (self.value / 100))
        return min(self.value, subtotal)


ORDER_STATUSES = ["pending", "preparing", "ready", "delivered"]
ORDER_CHANNELS = ["whatsapp", "online"]


class Order(db.Model):
    __tablename__ = "orders"

    id = db.Column(db.Integer, primary_key=True)
    order_number = db.Column(db.String(20), unique=True, nullable=False)
    customer_name = db.Column(db.String(120), default="Guest")
    customer_phone = db.Column(db.String(30), default="")
    channel = db.Column(db.String(20), default="whatsapp")
    status = db.Column(db.String(20), default="pending")

    subtotal = db.Column(db.Integer, default=0)
    delivery_fee = db.Column(db.Integer, default=0)
    tax = db.Column(db.Integer, default=0)
    discount = db.Column(db.Integer, default=0)
    total = db.Column(db.Integer, default=0)
    coupon_code = db.Column(db.String(30), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    items = db.relationship(
        "OrderItem", backref="order", lazy=True, cascade="all, delete-orphan"
    )

    @staticmethod
    def generate_order_number():
        return "SP" + secrets.token_hex(3).upper()

    def item_count(self):
        return sum(i.qty for i in self.items)

    def to_dict(self):
        return {
            "id": self.id,
            "order_number": self.order_number,
            "customer_name": self.customer_name,
            "channel": self.channel,
            "status": self.status,
            "total": self.total,
            "item_count": self.item_count(),
            "created_at": self.created_at.strftime("%d %b %Y, %I:%M %p"),
        }


class OrderItem(db.Model):
    __tablename__ = "order_items"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False)
    menu_item_id = db.Column(db.Integer, db.ForeignKey("menu_items.id"), nullable=True)
    name = db.Column(db.String(120), nullable=False)  # snapshot at time of order
    price = db.Column(db.Integer, nullable=False)      # snapshot at time of order
    emoji = db.Column(db.String(10), default="🍽️")
    qty = db.Column(db.Integer, default=1)


class SiteContent(db.Model):
    """Simple key/value store so any text on the public site can be edited
    from the Admin > Content tab without touching code."""

    __tablename__ = "site_content"

    key = db.Column(db.String(80), primary_key=True)
    value = db.Column(db.Text, default="")

    @staticmethod
    def get(key, default=""):
        row = SiteContent.query.get(key)
        return row.value if row else default

    @staticmethod
    def set(key, value):
        row = SiteContent.query.get(key)
        if row:
            row.value = value
        else:
            row = SiteContent(key=key, value=value)
            db.session.add(row)
