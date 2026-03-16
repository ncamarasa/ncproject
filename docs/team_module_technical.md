# Modulo Equipo - Diseno Tecnico

## Alcance
Se agrega un modulo principal `Equipo` para centralizar recursos, roles, disponibilidad, costos y asignaciones a clientes/proyectos/tareas.

## Modelo de datos
- `resources`: persona operativa (interna o tercerizada), con baja logica.
- `team_roles`: catalogo unico de roles operativos.
- `resource_role`: relacion N-N entre recurso y rol.
- `resource_availability`: historial de capacidad por vigencia.
- `resource_cost`: historial de costos por vigencia.
- `client_resource`, `project_resource`, `task_resource`: asignaciones por entidad.

## Integraciones
- Clientes:
  - `sales_executive_resource_id`
  - `account_manager_resource_id`
  - `delivery_manager_resource_id`
- Proyectos:
  - `project_manager_resource_id`
  - `commercial_manager_resource_id`
  - `functional_manager_resource_id`
  - `technical_manager_resource_id`
- Tareas:
  - `responsible_resource_id`
  - colaboradores via `task_resource`

## Reglas de negocio implementadas
- Recurso inactivo no asignable.
- Rol inactivo no asignable.
- Validacion de email de recurso y unicidad.
- Superposicion prohibida en `resource_availability` y `resource_cost`.
- Cierre automatico del costo anterior al crear uno nuevo posterior.
- Validacion recomendada: recurso de tarea debe estar asignado al proyecto.
- Auditoria automatica para entidades del modulo y asignaciones.

## Backend
- Nuevo blueprint: `project_manager.blueprints.team`.
- Endpoints:
  - ABM de recursos.
  - ABM de roles.
  - Alta/baja de roles por recurso.
  - Alta/baja de disponibilidad.
  - Alta/baja de costos.
  - Asignaciones a cliente/proyecto/tarea.

## Frontend
- Menu principal: `Equipo`.
- Pantallas:
  - `team/resource_list.html`
  - `team/resource_form.html`
  - `team/resource_detail.html`
  - `team/role_list.html`
  - `team/role_form.html`

## Seguridad y permisos
- Nuevos permisos:
  - `team.view`
  - `team.edit`
- Se agregan al admin por migracion y por comando `create-admin`.

## Testing
- Nuevo set: `tests/test_team_business_rules.py`
  - unicidad email
  - vigencias sin solapamiento
  - cierre de costo previo
  - validacion de asignaciones
  - consistencia tarea-proyecto

## Evolucion recomendada
- Reemplazar todos los campos de texto legacy por referencias FK en UI secundaria.
- Agregar calculo de carga/capacidad por semana usando `resource_availability`.
- Agregar costeo planificado/real por fecha efectiva en imputaciones.
