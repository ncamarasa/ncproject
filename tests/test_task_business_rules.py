import os
import tempfile
import unittest
from datetime import date
from decimal import Decimal

from project_manager import create_app
from project_manager.blueprints.tasks.routes import _validate_task_payload
from project_manager.extensions import db
from project_manager.models import AuditTrailLog, Client, Project, Task
from project_manager.services.task_business_rules import (
    calculate_parent_rollup,
    is_blocked_status,
    is_closed_status,
    recalculate_parent_task,
    validate_parent_assignment,
)


class TaskBusinessRulesTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fd, cls.db_path = tempfile.mkstemp(prefix="ncproject_tasks_", suffix=".db")
        os.close(fd)
        os.environ["DATABASE_URL"] = f"sqlite:///{cls.db_path}"
        cls.app = create_app()
        cls.app.config["TESTING"] = True

    @classmethod
    def tearDownClass(cls):
        try:
            os.remove(cls.db_path)
        except OSError:
            pass

    def setUp(self):
        with self.app.app_context():
            db.drop_all()
            db.create_all()
            client = Client(name="Cliente Test")
            db.session.add(client)
            db.session.flush()
            project = Project(
                name="Proyecto Test",
                client_id=client.id,
                project_type="Implementación",
                status="Activo",
                priority="Alta",
                owner="owner",
                is_active=True,
            )
            db.session.add(project)
            db.session.commit()
            self.project_id = project.id

    def _task(self, **kwargs):
        defaults = {
            "project_id": self.project_id,
            "title": "Tarea",
            "status": "Pendiente",
            "progress_percent": 0,
            "is_milestone": False,
            "is_active": True,
        }
        defaults.update(kwargs)
        task = Task(**defaults)
        db.session.add(task)
        db.session.flush()
        return task

    def test_validate_parent_assignment_rejects_third_level(self):
        with self.app.app_context():
            parent = self._task(title="Padre")
            child = self._task(title="Hija", parent_task_id=parent.id)
            db.session.commit()

            errors = validate_parent_assignment(self.project_id, child.id, current_task_id=None)
            self.assertTrue(any("Máximo 2 niveles" in e for e in errors))

    def test_validate_parent_assignment_rejects_circularity(self):
        with self.app.app_context():
            parent = self._task(title="Padre")
            child = self._task(title="Hija", parent_task_id=parent.id)
            db.session.commit()

            errors = validate_parent_assignment(self.project_id, child.id, current_task_id=parent.id)
            self.assertTrue(any("circularidad" in e.lower() for e in errors))

    def test_rollup_weighted_progress_and_dates(self):
        with self.app.app_context():
            parent = self._task(title="Padre")
            t1 = self._task(
                title="S1",
                parent_task_id=parent.id,
                progress_percent=50,
                estimated_hours=Decimal("10"),
                start_date=date(2026, 3, 1),
                due_date=date(2026, 3, 5),
            )
            t2 = self._task(
                title="S2",
                parent_task_id=parent.id,
                progress_percent=100,
                estimated_hours=Decimal("30"),
                start_date=date(2026, 3, 3),
                due_date=date(2026, 3, 10),
            )
            rollup = calculate_parent_rollup([t1, t2])
            self.assertEqual(rollup["start_date"], date(2026, 3, 1))
            self.assertEqual(rollup["due_date"], date(2026, 3, 10))
            self.assertEqual(rollup["progress_percent"], 88)

    def test_recalculate_parent_updates_and_audits(self):
        with self.app.app_context():
            parent = self._task(title="Padre", progress_percent=0)
            self._task(
                title="Hija 1",
                parent_task_id=parent.id,
                progress_percent=20,
                start_date=date(2026, 3, 2),
                due_date=date(2026, 3, 4),
            )
            self._task(
                title="Hija 2",
                parent_task_id=parent.id,
                progress_percent=80,
                start_date=date(2026, 3, 1),
                due_date=date(2026, 3, 6),
            )
            changed = recalculate_parent_task(parent.id, reason="test", trigger_task_id=None)
            db.session.commit()

            self.assertTrue(changed)
            db.session.refresh(parent)
            self.assertEqual(parent.progress_percent, 50)
            self.assertEqual(parent.start_date, date(2026, 3, 1))
            self.assertEqual(parent.due_date, date(2026, 3, 6))
            self.assertIsNotNone(parent.rollup_updated_at)

            audit = db.session.query(AuditTrailLog).filter_by(table_name="tasks", record_id=str(parent.id), action="auto_recalc").first()
            self.assertIsNotNone(audit)

    def test_recalculate_parent_clears_values_when_no_subtasks(self):
        with self.app.app_context():
            parent = self._task(
                title="Padre",
                progress_percent=55,
                start_date=date(2026, 3, 5),
                due_date=date(2026, 3, 8),
            )
            child = self._task(title="Hija", parent_task_id=parent.id, progress_percent=55)
            db.session.commit()

            db.session.delete(child)
            db.session.flush()
            changed = recalculate_parent_task(parent.id, reason="child_removed", trigger_task_id=child.id)
            db.session.commit()

            self.assertTrue(changed)
            db.session.refresh(parent)
            self.assertIsNone(parent.start_date)
            self.assertIsNone(parent.due_date)
            self.assertEqual(parent.progress_percent, 0)

    def test_recalculate_parent_noop_is_audited(self):
        with self.app.app_context():
            parent = self._task(title="Padre", progress_percent=50)
            self._task(title="Hija 1", parent_task_id=parent.id, progress_percent=50)
            self._task(title="Hija 2", parent_task_id=parent.id, progress_percent=50)
            db.session.commit()

            first_changed = recalculate_parent_task(parent.id, reason="initial", trigger_task_id=None)
            db.session.commit()
            self.assertFalse(first_changed)

            audit = (
                db.session.query(AuditTrailLog)
                .filter_by(table_name="tasks", record_id=str(parent.id), action="auto_recalc")
                .order_by(AuditTrailLog.id.desc())
                .first()
            )
            self.assertIsNotNone(audit)
            self.assertIn("noop", (audit.new_values or {}).get("reason", ""))

    def test_validate_payload_blocks_manual_fields_for_parent_with_subtasks(self):
        with self.app.app_context():
            parent = self._task(
                title="Padre",
                progress_percent=40,
                start_date=date(2026, 3, 1),
                due_date=date(2026, 3, 10),
            )
            self._task(title="Hija", parent_task_id=parent.id, status="Pendiente")
            db.session.commit()

            payload, errors = _validate_task_payload(
                self.project_id,
                {
                    "title": "Padre editado",
                    "creator": "tester",
                    "status": "Completada",
                    "progress_percent": "100",
                    "start_date": "2026-03-02",
                    "due_date": "2026-03-11",
                },
                current_task_id=parent.id,
                current_task=parent,
            )
            self.assertIsInstance(payload, dict)
            joined = " | ".join(errors).lower()
            self.assertIn("avance del padre", joined)
            self.assertIn("fechas del padre", joined)
            self.assertIn("no se puede cerrar", joined)

    def test_status_helpers(self):
        self.assertTrue(is_closed_status("Completada"))
        self.assertTrue(is_closed_status("DONE"))
        self.assertTrue(is_blocked_status("Bloqueada"))
        self.assertTrue(is_blocked_status("On Hold"))
        self.assertFalse(is_blocked_status("En progreso"))


if __name__ == "__main__":
    unittest.main()
