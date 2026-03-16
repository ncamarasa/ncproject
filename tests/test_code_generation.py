import os
import tempfile
import unittest

from project_manager import create_app
from project_manager.extensions import db
from project_manager.models import Client, Project
from project_manager.services.code_generation import (
    generate_client_code,
    generate_project_code,
)


class CodeGenerationTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fd, cls.db_path = tempfile.mkstemp(prefix="ncproject_codes_", suffix=".db")
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

    def test_generate_client_code_uses_prefix_and_sequence(self):
        with self.app.app_context():
            code_1 = generate_client_code(Client, Client.client_code, "Lafage Colombia")
            self.assertEqual(code_1, "LAF01")

            db.session.add(Client(name="Lafage Colombia", client_code=code_1))
            db.session.flush()

            code_2 = generate_client_code(Client, Client.client_code, "Lafage SA")
            self.assertEqual(code_2, "LAF02")

            code_other = generate_client_code(Client, Client.client_code, "Acme")
            self.assertEqual(code_other, "ACM01")

    def test_generate_project_code_uses_client_code_sequence(self):
        with self.app.app_context():
            client = Client(name="Lafage Colombia", client_code="LAF01")
            db.session.add(client)
            db.session.flush()

            project_1 = generate_project_code(Project, Project.project_code, client.client_code)
            self.assertEqual(project_1, "LAF01-001")

            db.session.add(
                Project(
                    name="Proyecto 1",
                    project_code=project_1,
                    client_id=client.id,
                    project_type="Implementacion",
                    status="Activo",
                    priority="Alta",
                    owner="owner",
                    is_active=True,
                )
            )
            db.session.flush()

            project_2 = generate_project_code(Project, Project.project_code, client.client_code)
            self.assertEqual(project_2, "LAF01-002")

    def test_generate_project_code_rejects_invalid_client_code(self):
        with self.app.app_context():
            with self.assertRaises(ValueError):
                generate_project_code(Project, Project.project_code, "LAF26-001")


if __name__ == "__main__":
    unittest.main()
