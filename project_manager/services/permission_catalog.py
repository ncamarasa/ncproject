from sqlalchemy import select

from project_manager.extensions import db
from project_manager.models import Permission, Role, RolePermission


PERMISSION_CATALOG: list[tuple[str, str, str]] = [
    ("main.view", "Ver home", "main"),
    ("clients.view", "Ver clientes", "clients"),
    ("clients.edit", "Editar clientes", "clients"),
    ("clients.create", "Crear clientes", "clients"),
    ("clients.delete", "Eliminar clientes", "clients"),
    ("clients.interactions.manage", "Gestionar interacciones de clientes", "clients"),
    ("clients.documents.manage", "Gestionar documentos de clientes", "clients"),
    ("contracts.view", "Ver contratos de clientes", "clients"),
    ("contracts.edit", "Editar contratos de clientes", "clients"),
    ("contracts.manage", "Gestionar contratos de clientes", "clients"),
    ("projects.view", "Ver proyectos", "projects"),
    ("projects.edit", "Editar proyectos", "projects"),
    ("projects.create", "Crear proyectos", "projects"),
    ("projects.delete", "Eliminar proyectos", "projects"),
    ("projects.stakeholders.manage", "Gestionar stakeholders de proyectos", "projects"),
    ("projects.assignments.manage", "Gestionar asignaciones de proyectos", "projects"),
    ("projects.financials.view", "Ver métricas financieras de proyectos", "projects"),
    ("tasks.view", "Ver tareas", "tasks"),
    ("tasks.edit", "Editar tareas", "tasks"),
    ("tasks.create", "Crear tareas", "tasks"),
    ("tasks.delete", "Eliminar tareas", "tasks"),
    ("tasks.status.update", "Actualizar estado de tareas", "tasks"),
    ("tasks.dependencies.manage", "Gestionar dependencias de tareas", "tasks"),
    ("tasks.comments.manage", "Gestionar comentarios de tareas", "tasks"),
    ("tasks.attachments.manage", "Gestionar adjuntos de tareas", "tasks"),
    ("tasks.worklog.manage", "Gestionar carga de trabajo en tareas", "tasks"),
    ("tasks.gantt.view", "Ver gantt de tareas", "tasks"),
    ("work.view", "Ver mi trabajo", "work"),
    ("work.log_hours", "Registrar horas en mi trabajo", "work"),
    ("work.progress.update", "Actualizar avance desde mi trabajo", "work"),
    ("control.view", "Ver control PMO", "control"),
    ("control.baseline.manage", "Gestionar baseline de proyectos", "control"),
    ("control.health.view", "Ver salud de proyectos", "control"),
    ("control.timesheets.approve", "Aprobar timesheets", "control"),
    ("control.periods.manage", "Gestionar períodos de timesheets", "control"),
    ("team.view", "Ver equipo", "team"),
    ("team.edit", "Editar equipo", "team"),
    ("team.resources.manage", "Gestionar recursos del equipo", "team"),
    ("team.assignments.manage", "Gestionar asignaciones del equipo", "team"),
    ("team.calendar.view", "Ver calendario de equipo", "team"),
    ("team.costs.manage", "Gestionar costos del equipo", "team"),
    ("settings.view", "Ver configuración", "settings"),
    ("settings.edit", "Editar configuración", "settings"),
    ("settings.catalogs.manage", "Gestionar catálogos de configuración", "settings"),
    ("users.manage", "Administrar usuarios", "users"),
    ("users.view", "Ver usuarios", "users"),
    ("roles.manage", "Administrar roles", "users"),
    ("auth.reset_password", "Resetear contraseñas", "users"),
    ("audit.view", "Ver auditoría", "audit"),
    ("audit.export", "Exportar auditoría", "audit"),
]


def ensure_permission_catalog() -> list[Permission]:
    permissions: list[Permission] = []
    for key, label, module in PERMISSION_CATALOG:
        perm = db.session.execute(select(Permission).where(Permission.key == key)).scalar_one_or_none()
        if perm:
            perm.label = label
            perm.module = module
            perm.is_active = True
        else:
            perm = Permission(key=key, label=label, module=module, is_active=True)
            db.session.add(perm)
            db.session.flush()
        permissions.append(perm)
    return permissions


def ensure_role_permissions(role: Role, permission_keys: list[str]) -> None:
    if not permission_keys:
        return
    perms = db.session.execute(select(Permission).where(Permission.key.in_(permission_keys))).scalars().all()
    existing_ids = {
        item.permission_id
        for item in db.session.execute(select(RolePermission).where(RolePermission.role_id == role.id)).scalars().all()
    }
    for perm in perms:
        if perm.id in existing_ids:
            continue
        db.session.add(RolePermission(role_id=role.id, permission_id=perm.id))
