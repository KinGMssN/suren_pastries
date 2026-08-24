from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = "admin.login"
login_manager.login_message = "Please log in to access the admin panel."
login_manager.login_message_category = "warning"

# In-memory storage is fine here since Render runs a single Gunicorn worker
# for this app — no need for Redis at this scale.
limiter = Limiter(key_func=get_remote_address, default_limits=[])