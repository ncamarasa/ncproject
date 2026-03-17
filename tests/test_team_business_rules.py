import os
import tempfile
import unittest
from datetime import date

from project_manager import create_app
from project_manager.extensions import db
from project_manager.models import (
    Client,
    Project,
    ProjectResource,
    Resource,
    ResourceAvailability,
    ResourceCost,
    Task,
    TeamRole,
)
from project_manager.services.team_business_rules import (
    close_previous_cost_if_needed,
    sync_resource_full_name,
    validate_assignment,
    validate_availability_payload,
    validate_cost_payload,
    validate_resource_payload,
    validate_task_assignment_project_consistency,
)


class TeamBusinessRulesTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fd, cls.db_path = tempfile.mkstemp(prefix="ncproject_team_", suffix=".db")
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

            resource = Resource(
                first_name="Ana",
                last_name="Perez",
                full_name="Ana Perez",
                email="ana@demo.com",
                resource_type="internal",
                is_active=True,
            )
            role = TeamRole(name="Project Manager", is_active=True)
            client = Client(name="Cliente X")
            db.session.add_all([resource, role, client])
            db.session.flush()
            self.resource_id = resource.id
            self.role_id = role.id
            self.client_id = client.id
            project = Project(
                name="Proyecto X",
                client_id=client.id,
                project_type="Implementacion",
                status="Planificado",
                priority="Alta",
                owner="owner",
                is_active=True,
            )
            db.session.add(project)
            db.session.flush()
            task = Task(project_id=project.id, title="Tarea 1", is_active=True)
            db.session.add(task)
            db.session.commit()
            self.project_id = project.id
            self.task_id = task.id

    def test_validate_resource_payload_unique_email(self):
        with self.app.app_context():
            payload = {
                "first_name": "Juan",
                "last_name": "Lopez",
                "email": "ana@demo.com",
                "resource_type": "internal",
            }
            errors = validate_resource_payload(payload)
            self.assertTrue(any("email" in e.lower() for e in errors))

    def test_sync_resource_full_name(self):
        with self.app.app_context():
            resource = Resource(first_name=" Mario ", last_name=" Rossi ", full_name="")
            sync_resource_full_name(resource)
            self.assertEqual(resource.full_name, "Mario Rossi")

    def test_validate_availability_overlap(self):
        with self.app.app_context():
            db.session.add(
                ResourceAvailability(
                    resource_id=self.resource_id,
                    availability_type="full_time",
                    weekly_hours=40,
                    valid_from=date(2026, 1, 1),
                    valid_to=date(2026, 1, 31),
                    is_active=True,
                )
            )
            db.session.commit()

            payload = {
                "availability_type": "part_time",
                "weekly_hours": 20,
                "daily_hours": None,
                "valid_from": date(2026, 1, 20),
                "valid_to": date(2026, 2, 10),
            }
            errors = validate_availability_payload(self.resource_id, payload)
            self.assertTrue(any("superposición" in e for e in errors))

    def test_validate_cost_overlap_and_auto_close_previous(self):
        with self.app.app_context():
            cost = ResourceCost(
                resource_id=self.resource_id,
                valid_from=date(2026, 1, 1),
                valid_to=None,
                hourly_cost=50,
                currency="USD",
                is_active=True,
            )
            db.session.add(cost)
            db.session.commit()

            payload = {
                "valid_from": date(2026, 2, 1),
                "valid_to": None,
                "hourly_cost": 60,
                "monthly_cost": None,
                "currency": "USD",
            }
            self.assertFalse(validate_cost_payload(self.resource_id, payload))
            close_previous_cost_if_needed(self.resource_id, payload["valid_from"])
            db.session.commit()
            db.session.refresh(cost)
            self.assertEqual(cost.valid_to, date(2026, 1, 31))

    def test_validate_assignment_inactive_resource_or_role(self):
        with self.app.app_context():
            resource = db.session.get(Resource, self.resource_id)
            role = db.session.get(TeamRole, self.role_id)
            resource.is_active = False
            role.is_active = False
            db.session.commit()
            errors = validate_assignment(self.resource_id, self.role_id)
            self.assertGreaterEqual(len(errors), 2)

    def test_task_assignment_requires_project_assignment(self):
        with self.app.app_context():
            errors = validate_task_assignment_project_consistency(self.task_id, self.resource_id)
            self.assertTrue(any("proyecto" in e.lower() for e in errors))

            db.session.add(
                ProjectResource(
                    project_id=self.project_id,
                    resource_id=self.resource_id,
                    role_id=self.role_id,
                    is_active=True,
                )
            )
            db.session.commit()

            errors = validate_task_assignment_project_consistency(self.task_id, self.resource_id)
            self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
