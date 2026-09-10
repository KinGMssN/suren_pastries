from datetime import datetime, timedelta

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user

from app.extensions import db, limiter
from app.auth import verify_totp
from app.models import AdminUser

admin_bp = Blueprint("admin", __name__)


@admin_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("5 per minute", methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("admin.dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        otp_code = request.form.get("otp_code", "").strip()
        user = AdminUser.query.filter_by(username=username).first()
        password_valid = user and user.check_password(password)
        totp_secret = current_app.config.get("ADMIN_TOTP_SECRET")
        second_factor_valid = not totp_secret or verify_totp(totp_secret, otp_code)

        if user and user.locked_until and user.locked_until > datetime.utcnow():
            flash("This account is temporarily locked. Please try again later.", "error")
        elif password_valid and second_factor_valid:
            user.failed_login_attempts = 0
            user.locked_until = None
            user.invalidate_sessions()
            db.session.commit()
            login_user(user)
            session.permanent = True
            session["admin_session_version"] = user.session_version
            session["admin_last_activity"] = datetime.utcnow().timestamp()
            next_url = request.args.get("next")
            return redirect(next_url or url_for("admin.dashboard"))
        else:
            if user:
                user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
                if user.failed_login_attempts >= current_app.config["ADMIN_MAX_LOGIN_FAILURES"]:
                    user.locked_until = datetime.utcnow() + timedelta(hours=24)
                db.session.commit()
            flash("Invalid username or password.", "error")

    return render_template("admin/login.html")


@admin_bp.route("/logout")
@login_required
def logout():
    logout_user()
    session.clear()
    return redirect(url_for("admin.login"))


@admin_bp.route("/logout-everywhere", methods=["POST"])
@login_required
def logout_everywhere():
    current_user.invalidate_sessions()
    db.session.commit()
    logout_user()
    session.clear()
    return redirect(url_for("admin.login"))


@admin_bp.route("/")
@login_required
def dashboard():
    active_tab = "menu" if current_user.is_menu_admin else "dashboard"
    return render_template("admin/dashboard.html", active_tab=active_tab)
