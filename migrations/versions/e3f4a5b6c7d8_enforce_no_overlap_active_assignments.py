"""enforce no overlap for active project/task assignments

Revision ID: e3f4a5b6c7d8
Revises: d1e2f3a4b5c6
Create Date: 2026-03-22 21:20:00.000000
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "e3f4a5b6c7d8"
down_revision = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None


def _upgrade_sqlite() -> None:
    op.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_project_resource_no_overlap_ins
        BEFORE INSERT ON project_resource
        WHEN NEW.is_active = 1
        BEGIN
          SELECT RAISE(ABORT, 'Overlap de asignacion activa en proyecto.')
          WHERE EXISTS (
            SELECT 1
            FROM project_resource pr
            WHERE pr.resource_id = NEW.resource_id
              AND pr.project_id = NEW.project_id
              AND pr.is_active = 1
              AND ifnull(NEW.start_date, '0001-01-01') <= ifnull(pr.end_date, '9999-12-31')
              AND ifnull(pr.start_date, '0001-01-01') <= ifnull(NEW.end_date, '9999-12-31')
          );
        END;
        """
    )
    op.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_project_resource_no_overlap_upd
        BEFORE UPDATE ON project_resource
        WHEN NEW.is_active = 1
        BEGIN
          SELECT RAISE(ABORT, 'Overlap de asignacion activa en proyecto.')
          WHERE EXISTS (
            SELECT 1
            FROM project_resource pr
            WHERE pr.resource_id = NEW.resource_id
              AND pr.project_id = NEW.project_id
              AND pr.is_active = 1
              AND pr.id <> NEW.id
              AND ifnull(NEW.start_date, '0001-01-01') <= ifnull(pr.end_date, '9999-12-31')
              AND ifnull(pr.start_date, '0001-01-01') <= ifnull(NEW.end_date, '9999-12-31')
          );
        END;
        """
    )
    op.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_task_resource_no_overlap_ins
        BEFORE INSERT ON task_resource
        WHEN NEW.is_active = 1
        BEGIN
          SELECT RAISE(ABORT, 'Overlap de asignacion activa en tarea.')
          WHERE EXISTS (
            SELECT 1
            FROM task_resource tr
            WHERE tr.resource_id = NEW.resource_id
              AND tr.task_id = NEW.task_id
              AND tr.is_active = 1
              AND ifnull(NEW.start_date, '0001-01-01') <= ifnull(tr.end_date, '9999-12-31')
              AND ifnull(tr.start_date, '0001-01-01') <= ifnull(NEW.end_date, '9999-12-31')
          );
        END;
        """
    )
    op.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_task_resource_no_overlap_upd
        BEFORE UPDATE ON task_resource
        WHEN NEW.is_active = 1
        BEGIN
          SELECT RAISE(ABORT, 'Overlap de asignacion activa en tarea.')
          WHERE EXISTS (
            SELECT 1
            FROM task_resource tr
            WHERE tr.resource_id = NEW.resource_id
              AND tr.task_id = NEW.task_id
              AND tr.is_active = 1
              AND tr.id <> NEW.id
              AND ifnull(NEW.start_date, '0001-01-01') <= ifnull(tr.end_date, '9999-12-31')
              AND ifnull(tr.start_date, '0001-01-01') <= ifnull(NEW.end_date, '9999-12-31')
          );
        END;
        """
    )


def _upgrade_postgresql() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_project_resource_no_overlap()
        RETURNS trigger AS $$
        BEGIN
          IF NEW.is_active THEN
            IF EXISTS (
              SELECT 1
              FROM project_resource pr
              WHERE pr.resource_id = NEW.resource_id
                AND pr.project_id = NEW.project_id
                AND pr.is_active = TRUE
                AND pr.id <> COALESCE(NEW.id, -1)
                AND COALESCE(NEW.start_date, DATE '-infinity') <= COALESCE(pr.end_date, DATE 'infinity')
                AND COALESCE(pr.start_date, DATE '-infinity') <= COALESCE(NEW.end_date, DATE 'infinity')
            ) THEN
              RAISE EXCEPTION 'Overlap de asignacion activa en proyecto.';
            END IF;
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_task_resource_no_overlap()
        RETURNS trigger AS $$
        BEGIN
          IF NEW.is_active THEN
            IF EXISTS (
              SELECT 1
              FROM task_resource tr
              WHERE tr.resource_id = NEW.resource_id
                AND tr.task_id = NEW.task_id
                AND tr.is_active = TRUE
                AND tr.id <> COALESCE(NEW.id, -1)
                AND COALESCE(NEW.start_date, DATE '-infinity') <= COALESCE(tr.end_date, DATE 'infinity')
                AND COALESCE(tr.start_date, DATE '-infinity') <= COALESCE(NEW.end_date, DATE 'infinity')
            ) THEN
              RAISE EXCEPTION 'Overlap de asignacion activa en tarea.';
            END IF;
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_project_resource_no_overlap
        BEFORE INSERT OR UPDATE ON project_resource
        FOR EACH ROW
        EXECUTE FUNCTION fn_project_resource_no_overlap();
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_task_resource_no_overlap
        BEFORE INSERT OR UPDATE ON task_resource
        FOR EACH ROW
        EXECUTE FUNCTION fn_task_resource_no_overlap();
        """
    )


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        _upgrade_sqlite()
        return
    if dialect == "postgresql":
        _upgrade_postgresql()
        return
    raise RuntimeError(f"Dialecto no soportado para esta migracion: {dialect}")


def _downgrade_sqlite() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_project_resource_no_overlap_ins")
    op.execute("DROP TRIGGER IF EXISTS trg_project_resource_no_overlap_upd")
    op.execute("DROP TRIGGER IF EXISTS trg_task_resource_no_overlap_ins")
    op.execute("DROP TRIGGER IF EXISTS trg_task_resource_no_overlap_upd")


def _downgrade_postgresql() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_project_resource_no_overlap ON project_resource")
    op.execute("DROP TRIGGER IF EXISTS trg_task_resource_no_overlap ON task_resource")
    op.execute("DROP FUNCTION IF EXISTS fn_project_resource_no_overlap()")
    op.execute("DROP FUNCTION IF EXISTS fn_task_resource_no_overlap()")


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        _downgrade_sqlite()
        return
    if dialect == "postgresql":
        _downgrade_postgresql()
        return
    raise RuntimeError(f"Dialecto no soportado para esta migracion: {dialect}")
