from functools import wraps

from flask import abort, jsonify, request
from flask_login import current_user


def admin_required(view_func):
    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        return view_func(*args, **kwargs)

    return wrapped_view


def api_login_required(view_func):
    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify({"error": "Authentication required."}), 401
        return view_func(*args, **kwargs)

    return wrapped_view


def api_admin_required(view_func):
    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify({"error": "Authentication required."}), 401
        if not current_user.is_admin:
            return jsonify({"error": "Admin access required."}), 403
        return view_func(*args, **kwargs)

    return wrapped_view


def owner_or_admin(item_owner_id):
    return current_user.is_authenticated and (
        current_user.is_admin or current_user.id == item_owner_id
    )
