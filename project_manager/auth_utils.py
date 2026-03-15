from functools import wraps

from flask import abort, flash, g, redirect, request, session, url_for
from sqlalchemy import select

from project_manager.extensions import db
from project_manager.models import (
    Permission,
    RolePermission,
    User,
    UserClientAssignment,
    UserProjectAssignment,
)


def login_required(view_func):
    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        if g.user is None:
            flash("Debes iniciar sesión para continuar.", "warning")
            return redirect(url_for("auth.login"))
        return view_func(*args, **kwargs)

    return wrapped_view


def _permission_keys_for_user(user: User) -> set[str]:
    if not user or not user.role_id:
        return set()
    cache_key = f"_perm_keys_user_{user.id}_role_{user.role_id}"
    cached = getattr(g, cache_key, None)
    if cached is not None:
        return cached
    rows = db.session.execute(
        select(Permission.key)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .where(
            RolePermission.role_id == user.role_id,
            Permission.is_active.is_(True),
        )
    ).scalars()
    keys = set(rows)
    setattr(g, cache_key, keys)
    return keys


def has_permission(user: User | None, permission_key: str) -> bool:
    if not user or not user.is_active:
        return False
    if user.username == "admin":
        return True
    return permission_key in _permission_keys_for_user(user)


def _deny(message: str = "No tienes permisos para realizar esta acción."):
    flash(message, "danger")
    if request.referrer:
        return redirect(request.referrer)
    return redirect(url_for("main.home"))


def require_permission(permission_key: str, *, write: bool = False):
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(*args, **kwargs):
            if g.user is None:
                flash("Debes iniciar sesión para continuar.", "warning")
                return redirect(url_for("auth.login"))
            if write and g.user.read_only:
                return _deny("Tu usuario es de solo lectura.")
            if not has_permission(g.user, permission_key):
                return _deny()
            return view_func(*args, **kwargs)

        return wrapped

    return decorator


def can_access_client(user: User | None, client_id: int) -> bool:
    if not user or not user.is_active:
        return False
    if user.username == "admin" or user.full_access:
        return True
    exists = db.session.execute(
        select(UserClientAssignment.id).where(
            UserClientAssignment.user_id == user.id,
            UserClientAssignment.client_id == client_id,
        )
    ).scalar_one_or_none()
    return exists is not None


def can_access_project(user: User | None, project_id: int) -> bool:
    if not user or not user.is_active:
        return False
    if user.username == "admin" or user.full_access:
        return True
    exists = db.session.execute(
        select(UserProjectAssignment.id).where(
            UserProjectAssignment.user_id == user.id,
            UserProjectAssignment.project_id == project_id,
        )
    ).scalar_one_or_none()
    return exists is not None


def allowed_client_ids(user: User | None) -> list[int] | None:
    if not user or not user.is_active:
        return []
    if user.username == "admin" or user.full_access:
        return None
    rows = db.session.execute(
        select(UserClientAssignment.client_id).where(UserClientAssignment.user_id == user.id)
    ).scalars().all()
    return list(rows)


def allowed_project_ids(user: User | None) -> list[int] | None:
    if not user or not user.is_active:
        return []
    if user.username == "admin" or user.full_access:
        return None
    rows = db.session.execute(
        select(UserProjectAssignment.project_id).where(UserProjectAssignment.user_id == user.id)
    ).scalars().all()
    return list(rows)


def require_client_scope(client_id: int):
    if not can_access_client(g.user, client_id):
        abort(403)


def require_project_scope(project_id: int):
    if not can_access_project(g.user, project_id):
        abort(403)


def load_logged_in_user() -> None:
    user_id = session.get("user_id")
    if user_id is None:
        g.user = None
    else:
        user = db.session.get(User, user_id)
        if not user or not user.is_active:
            session.clear()
            g.user = None
        else:
            g.user = user
