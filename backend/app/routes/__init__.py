from backend.app.routes.admin import admin_bp
from backend.app.routes.api import api_bp
from backend.app.routes.auth import auth_bp
from backend.app.routes.claims import claims_bp
from backend.app.routes.main import main_bp
from backend.app.routes.items import items_bp

__all__ = ["admin_bp", "api_bp", "auth_bp", "claims_bp", "items_bp", "main_bp"]
