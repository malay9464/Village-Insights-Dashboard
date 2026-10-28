import csv
import io
import tempfile
import unittest
from pathlib import Path

import app as project


class AppTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        project.app.config.update(TESTING=True, DATABASE=str(Path(self.temp.name) / "users.db"))
        project.init_db()
        self.client = project.app.test_client()
        self.csrf = self.client.get("/api/session").get_json()["csrf_token"]

    def tearDown(self):
        self.temp.cleanup()

    def post(self, path, payload):
        return self.client.post(path, json=payload, headers={"X-CSRF-Token": self.csrf})

    def signup_and_login(self):
        response = self.post("/api/signup", {"full_name": "Test User", "username": "test_user", "password": "Password123", "confirm_password": "Password123", "recovery_code": "recover-me-123"})
        self.assertEqual(response.status_code, 200, response.get_json())
        response = self.post("/api/login", {"username": "test_user", "password": "Password123"})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.csrf = response.get_json()["csrf_token"]

    def test_auth_and_recovery(self):
        self.assertEqual(self.client.get("/api/dashboard").status_code, 401)
        self.signup_and_login()
        duplicate = self.post("/api/signup", {"full_name": "Test User", "username": "TEST_USER", "password": "Password123", "confirm_password": "Password123", "recovery_code": "recover-me-123"})
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(self.post("/api/logout", {}).status_code, 200)
        self.csrf = self.client.get("/api/session").get_json()["csrf_token"]
        self.assertEqual(self.post("/api/forgot-password", {"username": "test_user", "recovery_code": "recover-me-123", "new_password": "NewPassword123"}).status_code, 200)
        self.assertEqual(self.post("/api/login", {"username": "test_user", "password": "NewPassword123"}).status_code, 200)

    def test_dashboard_filters_paging_and_export(self):
        self.signup_and_login()
        filters = self.client.get("/api/filters").get_json()
        self.assertEqual(filters["years"], [2024])
        self.assertEqual(len(filters["villages"]), 3500)
        overview = self.client.get("/api/dashboard?year=2024").get_json()
        self.assertEqual(overview["kpis"]["villages"], 3500)
        self.assertGreater(overview["kpis"]["population"], 0)
        sample = filters["villages"][0]
        page = self.client.get("/api/villages?year=2024&village=" + sample).get_json()
        self.assertEqual(page["total"], 1)
        self.assertEqual(page["rows"][0]["Village"], sample)
        paged = self.client.get("/api/villages?per_page=25&page=2").get_json()
        self.assertEqual(len(paged["rows"]), 25)
        self.assertEqual(paged["page"], 2)
        self.assertEqual(self.client.get("/api/villages?page=nope").status_code, 400)
        response = self.client.get("/api/export?year=2024&taluka=" + filters["talukas"][0])
        rows = list(csv.DictReader(io.StringIO(response.get_data(as_text=True))))
        expected = len(project.DATA[project.DATA["Taluka"] == filters["talukas"][0]])
        self.assertEqual(len(rows), expected)
        self.assertEqual(len(rows[0]), 58)

    def test_crop_filter_only_changes_agriculture_and_employment(self):
        self.signup_and_login()
        crop = project.DATA["Main_Crop"].dropna().iloc[0]
        full = self.client.get("/api/dashboard?year=2024").get_json()
        scoped = self.client.get(f"/api/dashboard?year=2024&crop={crop}").get_json()

        # Crop is a subject filter, not a demographic or infrastructure filter.
        self.assertEqual(scoped["kpis"], full["kpis"])
        self.assertEqual(scoped["population_by_taluka"], full["population_by_taluka"])
        self.assertEqual(scoped["households_by_taluka"], full["households_by_taluka"])
        self.assertEqual(scoped["literacy_by_taluka"], full["literacy_by_taluka"])
        self.assertEqual(scoped["services"], full["services"])
        self.assertEqual(scoped["gender"], full["gender"])
        self.assertEqual(scoped["age"], full["age"])
        self.assertLess(scoped["agriculture_kpis"]["villages"], full["agriculture_kpis"]["villages"])
        self.assertLess(scoped["agriculture_kpis"]["area"], full["agriculture_kpis"]["area"])
        self.assertLess(scoped["agriculture_kpis"]["total_workers"], full["agriculture_kpis"]["total_workers"])
        self.assertNotEqual(scoped["agriculture_kpis"]["women_workforce"], full["agriculture_kpis"]["women_workforce"])
        self.assertEqual({item["label"] for item in scoped["crop_area"]}, {crop})
        self.assertLess(sum(item["value"] for item in scoped["workforce"]), sum(item["value"] for item in full["workforce"]))

        taluka = project.DATA["Taluka"].dropna().iloc[0]
        options = self.client.get(f"/api/filters?taluka={taluka}").get_json()["villages"]
        self.assertTrue(options)
        self.assertTrue((project.DATA[project.DATA["Village_Name"].isin(options)]["Taluka"] == taluka).all())

    def test_csrf_and_invalid_credentials(self):
        bad = self.client.post("/api/signup", json={"full_name": "Valid Name", "username": "validid", "password": "Password123", "confirm_password": "Password123", "recovery_code": "recover123"})
        self.assertEqual(bad.status_code, 400)
        response = self.post("/api/login", {"username": "missing", "password": "wrong"})
        self.assertEqual(response.status_code, 401)

    def test_pages_and_static_assets(self):
        home = self.client.get("/")
        self.assertEqual(home.status_code, 200)
        self.assertIn(b"Simulated", home.data)
        css = self.client.get("/static/styles.css")
        js = self.client.get("/static/app.js")
        self.assertEqual(css.status_code, 200)
        self.assertEqual(js.status_code, 200)
        css.close()
        js.close()


if __name__ == "__main__":
    unittest.main()
