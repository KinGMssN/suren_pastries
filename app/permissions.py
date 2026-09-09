from functools import wraps

from flask import jsonify
from flask_login import current_user


def menu_access_required(view):
    """Allow both full admins and menu-only admins to manage menu items."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if getattr(current_user, "role", "super_admin") not in {"super_admin", "menu_admin"}:
            return jsonify({"ok": False, "error": "Menu access required."}), 403
        return view(*args, **kwargs)

    return wrapped


def super_admin_required(view):
    """Restrict management endpoints to full administrators."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if getattr(current_user, "role", "super_admin") != "super_admin":
            return jsonify({"ok": False, "error": "Full admin access required."}), 403
        return view(*args, **kwargs)

    return wrapped