import secrets
from datetime import date
import unicodedata

from sqlalchemy import delete, select

from project_manager.extensions import db
from project_manager.models import ProjectResource, Role, User, UserProjectAssignment
from project_manager.services.permission_catalog import ensure_permission_catalog, ensure_role_permissions


ANALYST_ROLE_NAME = "Analista"
ANALYST_PERMISSION_KEYS = (
    "main.view",
    "projects.view",
    "work.view",
    "work.log_hours",
    "work.progress.update",
)


def _safe_strip(value: str | None) -> str:
    return (value or "").strip()


def _normalize_for_username(value: str | None) -> str:
    raw = _safe_strip(value).lower()
    normalized = unicodedata.normalize("NFD", raw)
    cleaned = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    return "".join(ch for ch in cleaned if ch.isalnum())


def _username_seed_for_resource(resource) -> str:
    first_name = _normalize_for_username(getattr(resource, "first_name", None))
    last_name = _normalize_for_username(getattr(resource, "last_name", None))
    if first_name and last_name:
        return f"{first_name[0]}{last_name}"
    if last_name:
        return last_name
    if first_name:
        return first_name
    email = _safe_strip(getattr(resource, "email", None)).lower()
    if "@" in email:
        local = _normalize_for_username(email.split("@", 1)[0])
        if local:
            return local
    return "analista"


def _unique_username(base: str) -> str:
    root = (_normalize_for_username(base) or "analista")[:60]
    candidate = root
    suffix = 2
    while db.session.execute(select(User.id).where(User.username == candidate)).scalar_one_or_none() is not None:
        candidate = f"{root[:58]}{suffix}"
        suffix += 1
    return candidate


def ensure_analyst_role() -> Role:
    ensure_permission_catalog()
    role = db.session.execute(select(Role).where(Role.name == ANALYST_ROLE_NAME)).scalar_one_or_none()
    if not role:
        role = Role(
            name=ANALYST_ROLE_NAME,
            description="Acceso operativo a Home, Proyectos asignados y Mi Trabajo.",
            is_active=True,
            is_system=True,
            is_editable=True,
            is_deletable=True,
        )
        db.session.add(role)
        db.session.flush()
    elif not role.is_active:
        role.is_active = True

    ensure_role_permissions(role, list(ANALYST_PERMISSION_KEYS))
    return role


def provision_analyst_user_for_resource(resource) -> tuple[User | None, str | None, bool]:
    email = _safe_strip(getattr(resource, "email", None)).lower()
    if not email:
        return None, None, False

    existing_user = db.session.execute(select(User).where(User.email.ilike(email))).scalar_one_or_none()
    if existing_user:
        return existing_user, None, False

    role = ensure_analyst_role()
    username = _unique_username(_username_seed_for_resource(resource))
    temp_password = secrets.token_urlsafe(8)

    user = User(
        username=username,
        email=email,
        first_name=_safe_strip(getattr(resource, "first_name", None)) or None,
        last_name=_safe_strip(getattr(resource, "last_name", None)) or None,
        is_active=bool(getattr(resource, "is_active", True)),
        read_only=False,
        full_access=False,
        onboarding_date=date.today(),
        role_id=role.id,
    )
    user.set_password(temp_password)
    db.session.add(user)
    db.session.flush()
    return user, temp_password, True


def sync_user_project_scope_for_resource(resource_id: int) -> None:
    from project_manager.models import Resource  # import local to avoid circular imports

    resource = db.session.get(Resource, resource_id)
    if not resource:
        return
    email = _safe_strip(resource.email).lower()
    if not email:
        return
    user = db.session.execute(select(User).where(User.email.ilike(email))).scalar_one_or_none()
    if not user:
        return

    project_ids = db.session.execute(
        select(ProjectResource.project_id).where(
            ProjectResource.resource_id == resource_id,
            ProjectResource.is_active.is_(True),
        )
    ).scalars().all()
    unique_project_ids = sorted(set(project_ids))

    user.full_access = False

    if unique_project_ids:
        db.session.execute(
            delete(UserProjectAssignment).where(
                UserProjectAssignment.user_id == user.id,
                UserProjectAssignment.project_id.notin_(unique_project_ids),
            )
        )
    else:
        db.session.execute(
            delete(UserProjectAssignment).where(UserProjectAssignment.user_id == user.id)
        )

    existing_ids = set(
        db.session.execute(
            select(UserProjectAssignment.project_id).where(UserProjectAssignment.user_id == user.id)
        ).scalars().all()
    )
    for project_id in unique_project_ids:
        if project_id in existing_ids:
            continue
        db.session.add(UserProjectAssignment(user_id=user.id, project_id=project_id))


def sync_user_active_status_for_resource(resource_id: int, *, reactivate_on_enable: bool = False) -> User | None:
    from project_manager.models import Resource  # import local to avoid circular imports

    resource = db.session.get(Resource, resource_id)
    if not resource:
        return None
    email = _safe_strip(resource.email).lower()
    if not email:
        return None
    user = db.session.execute(select(User).where(User.email.ilike(email))).scalar_one_or_none()
    if not user:
        return None

    if not resource.is_active:
        user.is_active = False
    elif reactivate_on_enable:
        user.is_active = True
    return user


def user_for_resource(resource_id: int) -> User | None:
    from project_manager.models import Resource  # import local to avoid circular imports

    resource = db.session.get(Resource, resource_id)
    if not resource:
        return None
    email = _safe_strip(resource.email).lower()
    if not email:
        return None
    return db.session.execute(select(User).where(User.email.ilike(email))).scalar_one_or_none()
