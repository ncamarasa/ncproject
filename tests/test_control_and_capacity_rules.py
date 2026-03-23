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
    Task,
    TaskResource,
    TeamRole,
    TimesheetHeader,
    TimesheetPeriod,
)
from project_manager.services.control_service import approve_timesheet, reject_timesheet, submit_timesheet
from project_manager.services.team_business_rules import calculate_resource_net_availability


class ControlAndCapacityRulesTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fd, cls.db_path = tempfile.mkstemp(prefix="ncproject_control_capacity_", suffix=".db")
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

    def test_timesheet_state_machine_requires_valid_transitions(self):
        with self.app.app_context():
            resource = Resource(first_name="Ana", last_name="Perez", full_name="Ana Perez", resource_type="internal", is_active=True)
            db.session.add(resource)
            db.session.flush()

            header = TimesheetHeader(
                resource_id=resource.id,
                week_start=date(2026, 1, 5),
                week_end=date(2026, 1, 11),
                status="draft",
            )
            db.session.add(header)
            db.session.flush()

            with self.assertRaises(ValueError):
                approve_timesheet(header, approver_user_id=1)
            with self.assertRaises(ValueError):
                reject_timesheet(header, approver_user_id=1, comment="No cumple")

            submit_timesheet(header)
            self.assertEqual(header.status, "submitted")

            approve_timesheet(header, approver_user_id=1)
            self.assertEqual(header.status, "approved")

            with self.assertRaises(ValueError):
                submit_timesheet(header)

    def test_submit_timesheet_fails_when_period_is_closed(self):
        with self.app.app_context():
            resource = Resource(first_name="Ana", last_name="Perez", full_name="Ana Perez", resource_type="internal", is_active=True)
            period = TimesheetPeriod(
                start_date=date(2026, 1, 1),
                end_date=date(2026, 1, 31),
                is_closed=True,
            )
            db.session.add_all([resource, period])
            db.session.flush()

            header = TimesheetHeader(
                resource_id=resource.id,
                week_start=date(2026, 1, 5),
                week_end=date(2026, 1, 11),
                status="draft",
                period_id=period.id,
            )
            db.session.add(header)
            db.session.flush()

            with self.assertRaises(ValueError):
                submit_timesheet(header)

    def test_capacity_does_not_double_count_project_and_task_assignment_same_day(self):
        with self.app.app_context():
            resource = Resource(first_name="Ana", last_name="Perez", full_name="Ana Perez", resource_type="internal", is_active=True)
            role = TeamRole(name="Project Manager", is_active=True)
            client = Client(name="Cliente Test")
            db.session.add_all([resource, role, client])
            db.session.flush()

            project = Project(
                name="Proyecto Test",
                client_id=client.id,
                project_type="Implementacion",
                status="Activo",
                priority="Alta",
                owner="owner",
                is_active=True,
            )
            db.session.add(project)
            db.session.flush()

            task = Task(project_id=project.id, title="Tarea Test", is_active=True)
            db.session.add(task)
            db.session.flush()

            from project_manager.models import ResourceAvailability

            db.session.add(
                ResourceAvailability(
                    resource_id=resource.id,
                    availability_type="full_time",
                    weekly_hours=40,
                    daily_hours=8,
                    working_days="mon,tue,wed,thu,fri",
                    valid_from=date(2026, 1, 1),
                    valid_to=None,
                    is_active=True,
                )
            )
            db.session.add(
                ProjectResource(
                    project_id=project.id,
                    resource_id=resource.id,
                    role_id=role.id,
                    planned_daily_hours=4,
                    start_date=date(2026, 1, 5),
                    end_date=date(2026, 1, 5),
                    is_active=True,
                )
            )
            db.session.add(
                TaskResource(
                    task_id=task.id,
                    resource_id=resource.id,
                    role_id=role.id,
                    planned_daily_hours=4,
                    start_date=date(2026, 1, 5),
                    end_date=date(2026, 1, 5),
                    is_active=True,
                )
            )
            db.session.commit()

            result = calculate_resource_net_availability(resource.id, date(2026, 1, 5), date(2026, 1, 5))
            day = result["days"][0]
            self.assertEqual(day["base_hours"], 8.0)
            self.assertEqual(day["assigned_hours"], 4.0)
            self.assertEqual(day["net_available_hours"], 4.0)


if __name__ == "__main__":
    unittest.main()
