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
    ResourceAvailabilityException,
    ResourceCost,
    RoleSalePrice,
    Task,
    TeamCalendarHolidayConfig,
    TeamRole,
    User,
)
from project_manager.services.team_business_rules import (
    calculate_resource_net_availability,
    close_previous_role_sale_price_if_needed,
    close_previous_cost_if_needed,
    estimate_planned_daily_hours,
    find_applicable_cost_id,
    find_applicable_role_sale_price_id,
    normalize_working_days,
    resource_cost_usage_count,
    sync_resource_full_name,
    validate_assignment,
    validate_availability_payload,
    validate_availability_exception_payload,
    validate_cost_payload,
    validate_resource_payload,
    validate_role_sale_price_payload,
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
            user = User(username="tester", is_active=True, full_access=True, read_only=False)
            user.set_password("test123")
            db.session.add_all([resource, role, client, user])
            db.session.flush()
            self.resource_id = resource.id
            self.role_id = role.id
            self.client_id = client.id
            self.user_id = user.id
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

    def test_validate_availability_accepts_daily_or_weekly(self):
        with self.app.app_context():
            payload_daily_only = {
                "availability_type": "part_time",
                "weekly_hours": None,
                "daily_hours": 6,
                "working_days": "mon,tue,wed,thu,fri",
                "valid_from": date(2026, 1, 1),
                "valid_to": None,
            }
            errors_daily = validate_availability_payload(self.resource_id, payload_daily_only)
            self.assertEqual(errors_daily, [])

            payload_weekly_only = {
                "availability_type": "part_time",
                "weekly_hours": 30,
                "daily_hours": None,
                "working_days": "mon,tue,wed,thu,fri",
                "valid_from": date(2026, 2, 1),
                "valid_to": None,
            }
            errors_weekly = validate_availability_payload(self.resource_id, payload_weekly_only)
            self.assertEqual(errors_weekly, [])

            payload_none = {
                "availability_type": "part_time",
                "weekly_hours": None,
                "daily_hours": None,
                "working_days": "mon,tue,wed,thu,fri",
                "valid_from": date(2026, 3, 1),
                "valid_to": None,
            }
            errors_none = validate_availability_payload(self.resource_id, payload_none)
            self.assertTrue(any("horas diarias o semanales" in e.lower() for e in errors_none))

    def test_validate_availability_exception_overlap(self):
        with self.app.app_context():
            db.session.add(
                ResourceAvailabilityException(
                    resource_id=self.resource_id,
                    exception_type="vacation",
                    start_date=date(2026, 1, 10),
                    end_date=date(2026, 1, 20),
                    is_active=True,
                )
            )
            db.session.commit()
            payload = {
                "exception_type": "leave",
                "start_date": date(2026, 1, 15),
                "end_date": date(2026, 1, 25),
                "hours_lost": None,
            }
            errors = validate_availability_exception_payload(self.resource_id, payload)
            self.assertTrue(any("superposición" in e for e in errors))

    def test_validate_availability_exception_uses_allowed_types(self):
        with self.app.app_context():
            payload = {
                "exception_type": "holiday",
                "start_date": date(2026, 1, 15),
                "end_date": date(2026, 1, 16),
                "hours_lost": None,
            }
            errors = validate_availability_exception_payload(
                self.resource_id,
                payload,
                allowed_exception_types=["vacation", "leave"],
            )
            self.assertTrue(any("tipo de excepción inválido" in e.lower() for e in errors))

    def test_planned_daily_hours_estimate(self):
        with self.app.app_context():
            self.assertEqual(normalize_working_days(["mon", "wed", "fri"]), "mon,wed,fri")
            daily = estimate_planned_daily_hours(40, date(2026, 1, 5), date(2026, 1, 9))
            self.assertEqual(daily, 8)

    def test_calculate_resource_net_availability(self):
        with self.app.app_context():
            db.session.add(
                ResourceAvailability(
                    resource_id=self.resource_id,
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
                ResourceAvailabilityException(
                    resource_id=self.resource_id,
                    exception_type="vacation",
                    start_date=date(2026, 1, 6),
                    end_date=date(2026, 1, 6),
                    hours_lost=None,
                    is_active=True,
                )
            )
            db.session.add(
                ProjectResource(
                    project_id=self.project_id,
                    resource_id=self.resource_id,
                    role_id=self.role_id,
                    planned_daily_hours=4,
                    start_date=date(2026, 1, 5),
                    end_date=date(2026, 1, 7),
                    is_active=True,
                )
            )
            db.session.commit()

            result = calculate_resource_net_availability(self.resource_id, date(2026, 1, 5), date(2026, 1, 7))
            days = {item["date"]: item for item in result["days"]}
            self.assertEqual(days["2026-01-05"]["net_available_hours"], 4.0)
            self.assertEqual(days["2026-01-06"]["base_hours"], 0.0)
            self.assertEqual(days["2026-01-06"]["exception_hours"], 0.0)
            self.assertEqual(days["2026-01-06"]["net_available_hours"], 0.0)
            self.assertEqual(days["2026-01-06"]["overbooked_hours"], 4.0)

    def test_calculate_resource_net_availability_calendar_holiday(self):
        with self.app.app_context():
            resource = db.session.get(Resource, self.resource_id)
            resource.calendar_name = "Estados Unidos"
            db.session.add(
                ResourceAvailability(
                    resource_id=self.resource_id,
                    availability_type="full_time",
                    weekly_hours=40,
                    daily_hours=8,
                    working_days="mon,tue,wed,thu,fri",
                    valid_from=date(2026, 7, 1),
                    valid_to=None,
                    is_active=True,
                )
            )
            db.session.add(
                TeamCalendarHolidayConfig(
                    owner_user_id=self.user_id,
                    calendar_name="Estados Unidos",
                    holiday_date=date(2026, 7, 3),
                    label="Independence Day (observado)",
                    is_active=True,
                )
            )
            db.session.commit()

            result = calculate_resource_net_availability(
                self.resource_id,
                date(2026, 7, 3),
                date(2026, 7, 5),
                owner_user_id=self.user_id,
            )
            days = {item["date"]: item for item in result["days"]}
            self.assertEqual(days["2026-07-03"]["base_hours"], 0.0)
            self.assertEqual(days["2026-07-03"]["exception_hours"], 0.0)
            self.assertEqual(days["2026-07-03"]["net_available_hours"], 0.0)
            self.assertTrue(days["2026-07-03"]["calendar_holiday"])

    def test_calculate_resource_net_availability_counts_open_assignments(self):
        with self.app.app_context():
            db.session.add(
                ResourceAvailability(
                    resource_id=self.resource_id,
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
                    project_id=self.project_id,
                    resource_id=self.resource_id,
                    role_id=self.role_id,
                    planned_daily_hours=3,
                    start_date=date(2026, 1, 5),
                    end_date=None,
                    is_active=True,
                )
            )
            db.session.add(
                ProjectResource(
                    project_id=self.project_id,
                    resource_id=self.resource_id,
                    role_id=self.role_id,
                    planned_daily_hours=2,
                    start_date=None,
                    end_date=date(2026, 1, 9),
                    is_active=True,
                )
            )
            db.session.commit()

            result = calculate_resource_net_availability(self.resource_id, date(2026, 1, 8), date(2026, 1, 8))
            day = result["days"][0]
            self.assertEqual(day["base_hours"], 8.0)
            self.assertEqual(day["assigned_hours"], 5.0)
            self.assertEqual(day["net_available_hours"], 3.0)

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

    def test_validate_cost_requires_exactly_one_amount(self):
        with self.app.app_context():
            payload_none = {
                "valid_from": date(2026, 2, 1),
                "valid_to": None,
                "hourly_cost": None,
                "monthly_cost": None,
                "currency": "USD",
            }
            errors_none = validate_cost_payload(self.resource_id, payload_none)
            self.assertTrue(any("uno solo" in e.lower() for e in errors_none))

            payload_both = {
                "valid_from": date(2026, 2, 1),
                "valid_to": None,
                "hourly_cost": 80,
                "monthly_cost": 10000,
                "currency": "USD",
            }
            errors_both = validate_cost_payload(self.resource_id, payload_both)
            self.assertTrue(any("uno solo" in e.lower() for e in errors_both))

    def test_validate_cost_allows_monthly_only(self):
        with self.app.app_context():
            payload = {
                "valid_from": date(2026, 2, 1),
                "valid_to": None,
                "hourly_cost": None,
                "monthly_cost": 10000,
                "currency": "USD",
            }
            errors = validate_cost_payload(self.resource_id, payload)
            self.assertEqual(errors, [])

    def test_validate_assignment_inactive_resource_or_role(self):
        with self.app.app_context():
            resource = db.session.get(Resource, self.resource_id)
            role = db.session.get(TeamRole, self.role_id)
            resource.is_active = False
            role.is_active = False
            db.session.commit()
            errors = validate_assignment(self.resource_id, self.role_id)
            self.assertGreaterEqual(len(errors), 2)

    def test_find_applicable_cost_id_and_usage_count(self):
        with self.app.app_context():
            old_cost = ResourceCost(
                resource_id=self.resource_id,
                valid_from=date(2026, 1, 1),
                valid_to=date(2026, 1, 31),
                hourly_cost=50,
                currency="USD",
                is_active=True,
            )
            new_cost = ResourceCost(
                resource_id=self.resource_id,
                valid_from=date(2026, 2, 1),
                valid_to=None,
                hourly_cost=60,
                currency="USD",
                is_active=True,
            )
            db.session.add_all([old_cost, new_cost])
            db.session.flush()

            self.assertEqual(find_applicable_cost_id(self.resource_id, date(2026, 1, 15)), old_cost.id)
            self.assertEqual(find_applicable_cost_id(self.resource_id, date(2026, 2, 15)), new_cost.id)

            db.session.add(
                ProjectResource(
                    project_id=self.project_id,
                    resource_id=self.resource_id,
                    role_id=self.role_id,
                    resource_cost_id=new_cost.id,
                    is_active=True,
                )
            )
            db.session.commit()
            self.assertEqual(resource_cost_usage_count(new_cost.id), 1)

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

    def test_validate_role_sale_price_and_lookup(self):
        with self.app.app_context():
            sale_price = RoleSalePrice(
                role_id=self.role_id,
                valid_from=date(2026, 1, 1),
                valid_to=date(2026, 1, 31),
                hourly_price=120,
                currency="USD",
                is_active=True,
            )
            db.session.add(sale_price)
            db.session.commit()

            payload = {
                "valid_from": date(2026, 1, 20),
                "valid_to": date(2026, 2, 20),
                "hourly_price": 130,
                "monthly_price": None,
                "currency": "USD",
            }
            errors = validate_role_sale_price_payload(self.role_id, payload)
            self.assertTrue(any("superposición" in err.lower() for err in errors))
            self.assertEqual(find_applicable_role_sale_price_id(self.role_id, date(2026, 1, 15)), sale_price.id)

    def test_validate_role_sale_price_requires_exactly_one_amount(self):
        with self.app.app_context():
            payload_none = {
                "valid_from": date(2026, 3, 1),
                "valid_to": None,
                "hourly_price": None,
                "monthly_price": None,
                "currency": "USD",
            }
            payload_both = {
                "valid_from": date(2026, 3, 1),
                "valid_to": None,
                "hourly_price": 100,
                "monthly_price": 12000,
                "currency": "USD",
            }
            errors_none = validate_role_sale_price_payload(self.role_id, payload_none)
            errors_both = validate_role_sale_price_payload(self.role_id, payload_both)
            self.assertTrue(any("uno solo" in err.lower() for err in errors_none))
            self.assertTrue(any("uno solo" in err.lower() for err in errors_both))

    def test_close_previous_role_sale_price_and_lookup_latest(self):
        with self.app.app_context():
            first = RoleSalePrice(
                role_id=self.role_id,
                valid_from=date(2026, 1, 1),
                valid_to=None,
                hourly_price=100,
                currency="USD",
                is_active=True,
            )
            db.session.add(first)
            db.session.commit()

            new_start = date(2026, 2, 1)
            close_previous_role_sale_price_if_needed(self.role_id, new_start)
            second = RoleSalePrice(
                role_id=self.role_id,
                valid_from=new_start,
                valid_to=None,
                hourly_price=110,
                currency="USD",
                is_active=True,
            )
            db.session.add(second)
            db.session.commit()
            db.session.refresh(first)

            self.assertEqual(first.valid_to, date(2026, 1, 31))
            self.assertEqual(find_applicable_role_sale_price_id(self.role_id, date(2026, 1, 20)), first.id)
            self.assertEqual(find_applicable_role_sale_price_id(self.role_id, date(2026, 2, 15)), second.id)


if __name__ == "__main__":
    unittest.main()
