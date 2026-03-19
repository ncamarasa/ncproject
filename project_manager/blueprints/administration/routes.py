from datetime import date
from decimal import Decimal, InvalidOperation

from flask import abort, flash, g, redirect, render_template, request, url_for
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from project_manager.auth_utils import require_permission
from project_manager.blueprints.administration import bp
from project_manager.extensions import db
from project_manager.models import (
    AccessAuditLog,
    AuditTrailLog,
    Client,
    Permission,
    Project,
    RoleSalePrice,
    Role,
    RolePermission,
    User,
    UserClientAssignment,
    UserProjectAssignment,
    TeamRole,
)
from project_manager.services.default_catalogs import seed_default_catalogs_for_user
from project_manager.services.team_business_rules import (
    close_previous_role_sale_price_if_needed,
    validate_role_sale_price_payload,
)
from project_manager.utils.dates import parse_date_input


@bp.before_request
def _authorize_administration_module():
    if g.get("user") is None:
        flash("Debes iniciar sesión para continuar.", "warning")
        return redirect(url_for("auth.login"))


def _safe_strip(value: str | None) -> str:
    return (value or "").strip()


def _normalize_role_name(value: str | None) -> str:
    return " ".join(_safe_strip(value).split())


def _to_int(value: str | None, default: int = 0) -> int:
    try:
        num = int(value)
        return num if num >= 0 else default
    except (TypeError, ValueError):
        return default


def _to_bool(value: str | None) -> bool:
    return value in {"1", "true", "on", "yes", "si"}


def _to_decimal(value: str | None):
    if value in (None, ""):
        return None
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError):
        return None


_parse_date = parse_date_input


def _paginate(stmt, page: int, per_page: int = 12):
    return db.paginate(stmt, page=page, per_page=per_page, error_out=False)


def _role_in_use(role_id: int) -> bool:
    return db.session.execute(select(User.id).where(User.role_id == role_id).limit(1)).scalar_one_or_none() is not None


def _user_in_use(user_id: int) -> bool:
    has_client_assignments = (
        db.session.execute(select(UserClientAssignment.id).where(UserClientAssignment.user_id == user_id).limit(1))
        .scalar_one_or_none()
        is not None
    )
    has_project_assignments = (
        db.session.execute(select(UserProjectAssignment.id).where(UserProjectAssignment.user_id == user_id).limit(1))
        .scalar_one_or_none()
        is not None
    )
    return has_client_assignments or has_project_assignments


def _permission_tree():
    permissions = db.session.execute(select(Permission).where(Permission.is_active.is_(True)).order_by(Permission.module.asc(), Permission.label.asc())).scalars().all()
    module_labels = {
        "users": "Administración",
        "audit": "Auditoría",
        "clients": "Clientes",
        "projects": "Proyectos",
        "tasks": "Tareas",
        "team": "Equipo",
        "settings": "Configuración",
    }
    tree = {}
    for p in permissions:
        module_name = module_labels.get(p.module, p.module.replace("_", " ").title())
        tree.setdefault(module_name, []).append(p)
    return tree


@bp.route("/")
@require_permission("users.manage")
def list_users():
    page = _to_int(request.args.get("page"), default=1) or 1
    q = _safe_strip(request.args.get("q"))
    role_id = _to_int(request.args.get("role_id"))
    status = _safe_strip(request.args.get("status"))

    stmt = select(User).options(selectinload(User.role)).order_by(User.updated_at.desc())
    if q:
        token = f"%{q}%"
        stmt = stmt.where(
            or_(
                User.username.ilike(token),
                User.email.ilike(token),
                User.first_name.ilike(token),
                User.last_name.ilike(token),
            )
        )
    if role_id:
        stmt = stmt.where(User.role_id == role_id)
    if status in {"1", "0"}:
        stmt = stmt.where(User.is_active.is_(status == "1"))

    users_pagination = _paginate(stmt, page)
    roles = db.session.execute(select(Role).where(Role.is_active.is_(True)).order_by(Role.name.asc())).scalars().all()

    return render_template(
        "administration/user_list.html",
        users=users_pagination.items,
        users_pagination=users_pagination,
        roles=roles,
        filters={"q": q, "role_id": role_id, "status": status},
    )


@bp.route("/new", methods=["GET", "POST"])
@require_permission("users.manage", write=True)
def create_user():
    roles = db.session.execute(select(Role).where(Role.is_active.is_(True)).order_by(Role.name.asc())).scalars().all()
    clients = db.session.execute(select(Client).where(Client.is_active.is_(True)).order_by(Client.name.asc())).scalars().all()
    projects = db.session.execute(select(Project).where(Project.is_active.is_(True)).order_by(Project.name.asc())).scalars().all()

    if request.method == "POST":
        errors = []
        username = _safe_strip(request.form.get("username"))
        email = _safe_strip(request.form.get("email"))
        first_name = _safe_strip(request.form.get("first_name"))
        last_name = _safe_strip(request.form.get("last_name"))
        password = request.form.get("password", "")
        role_id = _to_int(request.form.get("role_id"))

        if len(username) < 3:
            errors.append("El username debe tener al menos 3 caracteres.")
        if len(password) < 8:
            errors.append("La contraseña inicial debe tener al menos 8 caracteres.")
        if db.session.execute(select(User.id).where(User.username.ilike(username))).scalar_one_or_none():
            errors.append("Ya existe un usuario con ese username.")
        if email and db.session.execute(select(User.id).where(User.email.ilike(email))).scalar_one_or_none():
            errors.append("Ya existe un usuario con ese email.")

        role = db.session.get(Role, role_id) if role_id else None
        if not role:
            errors.append("Debes seleccionar un rol válido.")

        if errors:
            for err in errors:
                flash(err, "danger")
            return render_template(
                "administration/user_form.html",
                user=None,
                is_edit=False,
                roles=roles,
                clients=clients,
                projects=projects,
                selected_clients=[str(x) for x in request.form.getlist("client_ids")],
                selected_projects=[str(x) for x in request.form.getlist("project_ids")],
                form_values=request.form,
            )

        user = User(
            username=username,
            email=email or None,
            first_name=first_name or None,
            last_name=last_name or None,
            is_active=_to_bool(request.form.get("is_active", "1")),
            read_only=_to_bool(request.form.get("read_only")),
            full_access=_to_bool(request.form.get("full_access", "1")),
            onboarding_date=date.today(),
            role_id=role.id,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.flush()
        seed_default_catalogs_for_user(user.id)

        if not user.full_access:
            for client_id in request.form.getlist("client_ids"):
                cid = _to_int(client_id)
                if cid:
                    db.session.add(UserClientAssignment(user_id=user.id, client_id=cid))
            for project_id in request.form.getlist("project_ids"):
                pid = _to_int(project_id)
                if pid:
                    db.session.add(UserProjectAssignment(user_id=user.id, project_id=pid))

        db.session.commit()
        flash("Usuario creado correctamente.", "success")
        return redirect(url_for("administration.list_users"))

    return render_template(
        "administration/user_form.html",
        user=None,
        is_edit=False,
        roles=roles,
        clients=clients,
        projects=projects,
        selected_clients=[],
        selected_projects=[],
        form_values={},
    )


@bp.route("/<int:user_id>/edit", methods=["GET", "POST"])
@require_permission("users.manage", write=True)
def edit_user(user_id: int):
    user = db.session.execute(
        select(User)
        .where(User.id == user_id)
        .options(selectinload(User.clients), selectinload(User.projects), selectinload(User.role))
    ).scalar_one_or_none()
    if not user:
        abort(404)

    roles = db.session.execute(select(Role).where(Role.is_active.is_(True)).order_by(Role.name.asc())).scalars().all()
    clients = db.session.execute(select(Client).where(Client.is_active.is_(True)).order_by(Client.name.asc())).scalars().all()
    projects = db.session.execute(select(Project).where(Project.is_active.is_(True)).order_by(Project.name.asc())).scalars().all()

    if request.method == "POST":
        errors = []
        username = _safe_strip(request.form.get("username"))
        email = _safe_strip(request.form.get("email"))

        if len(username) < 3:
            errors.append("El username debe tener al menos 3 caracteres.")
        if db.session.execute(select(User.id).where(User.id != user.id, User.username.ilike(username))).scalar_one_or_none():
            errors.append("Ya existe un usuario con ese username.")
        if email and db.session.execute(select(User.id).where(User.id != user.id, User.email.ilike(email))).scalar_one_or_none():
            errors.append("Ya existe un usuario con ese email.")

        role_id = _to_int(request.form.get("role_id"))
        role = db.session.get(Role, role_id) if role_id else None
        if not role:
            errors.append("Debes seleccionar un rol válido.")

        if errors:
            for err in errors:
                flash(err, "danger")
            return render_template(
                "administration/user_form.html",
                user=user,
                is_edit=True,
                roles=roles,
                clients=clients,
                projects=projects,
                selected_clients=[str(x) for x in request.form.getlist("client_ids")],
                selected_projects=[str(x) for x in request.form.getlist("project_ids")],
                form_values=request.form,
            )

        user.username = username
        user.email = email or None
        user.first_name = _safe_strip(request.form.get("first_name")) or None
        user.last_name = _safe_strip(request.form.get("last_name")) or None
        user.is_active = _to_bool(request.form.get("is_active"))
        user.read_only = _to_bool(request.form.get("read_only"))
        user.full_access = _to_bool(request.form.get("full_access"))
        user.role_id = role.id

        db.session.query(UserClientAssignment).filter_by(user_id=user.id).delete(synchronize_session=False)
        db.session.query(UserProjectAssignment).filter_by(user_id=user.id).delete(synchronize_session=False)

        if not user.full_access:
            for client_id in request.form.getlist("client_ids"):
                cid = _to_int(client_id)
                if cid:
                    db.session.add(UserClientAssignment(user_id=user.id, client_id=cid))
            for project_id in request.form.getlist("project_ids"):
                pid = _to_int(project_id)
                if pid:
                    db.session.add(UserProjectAssignment(user_id=user.id, project_id=pid))

        db.session.commit()
        flash("Usuario actualizado.", "success")
        return redirect(url_for("administration.list_users"))

    return render_template(
        "administration/user_form.html",
        user=user,
        is_edit=True,
        roles=roles,
        clients=clients,
        projects=projects,
        selected_clients=[str(item.client_id) for item in user.clients],
        selected_projects=[str(item.project_id) for item in user.projects],
        form_values={},
    )


@bp.route("/<int:user_id>/toggle", methods=["POST"])
@require_permission("users.manage", write=True)
def toggle_user(user_id: int):
    user = db.session.get(User, user_id)
    if not user:
        abort(404)
    if user.is_active and _user_in_use(user.id):
        flash("No se puede desactivar: el usuario tiene asignaciones activas.", "danger")
        return redirect(url_for("administration.list_users"))
    user.is_active = not user.is_active
    db.session.commit()
    flash("Estado de usuario actualizado.", "info")
    return redirect(url_for("administration.list_users"))


@bp.route("/<int:user_id>/reset-password", methods=["POST"])
@require_permission("auth.reset_password", write=True)
def reset_password(user_id: int):
    user = db.session.get(User, user_id)
    if not user:
        abort(404)
    new_password = _safe_strip(request.form.get("new_password"))
    if len(new_password) < 8:
        flash("La nueva contraseña debe tener al menos 8 caracteres.", "danger")
        return redirect(url_for("administration.list_users"))
    user.set_password(new_password)
    db.session.commit()
    flash(f"Contraseña reseteada para {user.username}.", "success")
    return redirect(url_for("administration.list_users"))


@bp.route("/roles", methods=["GET", "POST"])
@require_permission("users.manage")
def list_roles():
    if request.method == "POST" and g.user.read_only:
        flash("Tu usuario es de solo lectura.", "danger")
        return redirect(url_for("administration.list_roles"))
    permissions = _permission_tree()
    if request.method == "POST":
        if request.form.get("form_type") == "create_role":
            name = _normalize_role_name(request.form.get("name"))
            description = _safe_strip(request.form.get("description"))
            selected_permission_ids = [_to_int(x) for x in request.form.getlist("permission_ids")]
            selected_permission_ids = [x for x in selected_permission_ids if x]
            errors = []
            if len(name) < 2:
                errors.append("El nombre del rol debe tener al menos 2 caracteres.")
            if db.session.execute(
                select(Role.id).where(func.lower(Role.name) == name.lower())
            ).scalar_one_or_none():
                errors.append("Ya existe un rol con ese nombre.")
            if not selected_permission_ids:
                errors.append("Debes seleccionar al menos un permiso.")
            if errors:
                for err in errors:
                    flash(err, "danger")
            else:
                role = Role(
                    name=name,
                    description=description or None,
                    is_active=True,
                    is_system=False,
                    is_editable=True,
                    is_deletable=True,
                )
                db.session.add(role)
                db.session.flush()
                for pid in selected_permission_ids:
                    db.session.add(RolePermission(role_id=role.id, permission_id=pid))
                db.session.commit()
                flash("Rol creado.", "success")
                return redirect(url_for("administration.list_roles"))

    roles = db.session.execute(
        select(Role).options(selectinload(Role.permissions).selectinload(RolePermission.permission)).order_by(Role.name.asc())
    ).scalars().all()
    return render_template("administration/role_list.html", roles=roles, permission_tree=permissions)


@bp.route("/roles/<int:role_id>/edit", methods=["GET", "POST"])
@require_permission("users.manage", write=True)
def edit_role(role_id: int):
    role = db.session.execute(
        select(Role)
        .where(Role.id == role_id)
        .options(selectinload(Role.permissions).selectinload(RolePermission.permission))
    ).scalar_one_or_none()
    if not role:
        abort(404)
    if not role.is_editable:
        flash("No se puede editar: el rol es de sistema.", "danger")
        return redirect(url_for("administration.list_roles"))

    permissions = _permission_tree()
    if request.method == "POST":
        name = _normalize_role_name(request.form.get("name"))
        description = _safe_strip(request.form.get("description"))
        selected_permission_ids = [_to_int(x) for x in request.form.getlist("permission_ids")]
        selected_permission_ids = [x for x in selected_permission_ids if x]
        errors = []
        if len(name) < 2:
            errors.append("El nombre del rol debe tener al menos 2 caracteres.")
        if db.session.execute(
            select(Role.id).where(
                Role.id != role.id,
                func.lower(Role.name) == name.lower(),
            )
        ).scalar_one_or_none():
            errors.append("Ya existe un rol con ese nombre.")
        if not selected_permission_ids:
            errors.append("Debes seleccionar al menos un permiso.")
        if errors:
            for err in errors:
                flash(err, "danger")
        else:
            role.name = name
            role.description = description or None
            requested_active = _to_bool(request.form.get("is_active"))
            if role.is_active and not requested_active:
                if not role.is_deletable:
                    flash("No se puede desactivar: el rol es de sistema.", "danger")
                    return redirect(url_for("administration.list_roles"))
                if _role_in_use(role.id):
                    flash("No se puede desactivar: el rol está asignado a usuarios.", "danger")
                    return redirect(url_for("administration.list_roles"))
            role.is_active = requested_active
            db.session.query(RolePermission).filter_by(role_id=role.id).delete(synchronize_session=False)
            for pid in selected_permission_ids:
                db.session.add(RolePermission(role_id=role.id, permission_id=pid))
            db.session.commit()
            flash("Rol actualizado.", "success")
            return redirect(url_for("administration.list_roles"))

    selected_ids = {link.permission_id for link in role.permissions}
    return render_template(
        "administration/role_form.html",
        role=role,
        permission_tree=permissions,
        selected_permission_ids=selected_ids,
    )


@bp.route("/roles/<int:role_id>/toggle", methods=["POST"])
@require_permission("users.manage", write=True)
def toggle_role(role_id: int):
    role = db.session.get(Role, role_id)
    if not role:
        abort(404)
    if role.is_active:
        if not role.is_deletable:
            flash("No se puede desactivar: el rol es de sistema.", "danger")
            return redirect(url_for("administration.list_roles"))
        if _role_in_use(role.id):
            flash("No se puede desactivar: el rol está asignado a usuarios.", "danger")
            return redirect(url_for("administration.list_roles"))
    role.is_active = not role.is_active
    db.session.commit()
    flash("Estado del rol actualizado.", "info")
    return redirect(url_for("administration.list_roles"))


@bp.route("/team-role-prices", methods=["GET", "POST"])
@require_permission("users.manage")
def team_role_prices():
    roles = db.session.execute(select(TeamRole).where(TeamRole.is_active.is_(True)).order_by(TeamRole.name.asc())).scalars().all()
    prices = db.session.execute(
        select(RoleSalePrice)
        .join(TeamRole, TeamRole.id == RoleSalePrice.role_id)
        .where(TeamRole.is_active.is_(True))
        .options(selectinload(RoleSalePrice.role))
        .order_by(RoleSalePrice.valid_from.desc(), RoleSalePrice.id.desc())
    ).scalars().all()

    edit_id = _to_int(request.args.get("edit_id"))
    edit_price = db.session.get(RoleSalePrice, edit_id) if edit_id else None

    if request.method == "POST":
        if g.user.read_only:
            flash("Tu usuario es de solo lectura.", "danger")
            return redirect(url_for("administration.team_role_prices"))

        role_id = _to_int(request.form.get("role_id"))
        price_type = _safe_strip(request.form.get("price_type")).lower()
        amount = _to_decimal(request.form.get("price_amount"))
        payload = {
            "valid_from": _parse_date(request.form.get("valid_from")),
            "valid_to": _parse_date(request.form.get("valid_to")),
            "hourly_price": amount if price_type == "hourly" else None,
            "monthly_price": amount if price_type == "monthly" else None,
            "currency": _safe_strip(request.form.get("currency")).upper(),
            "observations": _safe_strip(request.form.get("observations")),
            "is_active": True,
        }

        target_id = _to_int(request.form.get("price_id"))
        current = db.session.get(RoleSalePrice, target_id) if target_id else None
        if target_id and not current:
            abort(404)

        errors = validate_role_sale_price_payload(role_id, payload, current_id=current.id if current else None)
        if errors:
            for err in errors:
                flash(err, "danger")
            return render_template(
                "administration/team_role_prices.html",
                roles=roles,
                prices=prices,
                edit_price=current,
                form_values=request.form,
            )

        close_previous_role_sale_price_if_needed(role_id, payload["valid_from"], current_id=current.id if current else None)
        if current:
            current.role_id = role_id
            current.valid_from = payload["valid_from"]
            current.valid_to = payload["valid_to"]
            current.hourly_price = payload["hourly_price"]
            current.monthly_price = payload["monthly_price"]
            current.currency = payload["currency"]
            current.observations = payload["observations"]
            flash("Precio de venta actualizado.", "success")
        else:
            db.session.add(RoleSalePrice(role_id=role_id, **payload))
            flash("Precio de venta creado.", "success")
        db.session.commit()
        return redirect(url_for("administration.team_role_prices"))

    return render_template(
        "administration/team_role_prices.html",
        roles=roles,
        prices=prices,
        edit_price=edit_price,
        form_values={},
    )


@bp.route("/audit/access")
@require_permission("audit.view")
def access_audit():
    page = _to_int(request.args.get("page"), default=1) or 1
    q = _safe_strip(request.args.get("q"))
    stmt = select(AccessAuditLog).order_by(AccessAuditLog.created_at.desc())
    if q:
        token = f"%{q}%"
        stmt = stmt.where(
            or_(
                AccessAuditLog.username.ilike(token),
                AccessAuditLog.event.ilike(token),
                AccessAuditLog.outcome.ilike(token),
                AccessAuditLog.reason.ilike(token),
            )
        )
    pagination = _paginate(stmt, page, per_page=25)
    return render_template(
        "administration/access_audit.html",
        logs=pagination.items,
        pagination=pagination,
        filters={"q": q},
    )


@bp.route("/audit/trail")
@require_permission("audit.view")
def trail_audit():
    page = _to_int(request.args.get("page"), default=1) or 1
    q = _safe_strip(request.args.get("q"))
    stmt = select(AuditTrailLog).order_by(AuditTrailLog.created_at.desc())
    if q:
        token = f"%{q}%"
        stmt = stmt.where(
            or_(
                AuditTrailLog.table_name.ilike(token),
                AuditTrailLog.record_id.ilike(token),
                AuditTrailLog.action.ilike(token),
            )
        )
    pagination = _paginate(stmt, page, per_page=25)
    return render_template(
        "administration/trail_audit.html",
        logs=pagination.items,
        pagination=pagination,
        filters={"q": q},
    )
