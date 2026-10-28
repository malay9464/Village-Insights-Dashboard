import csv
import io
import sqlite3
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
        payload = {"full_name": "Test User", "username": "test_user", "password": "Password123", "confirm_password": "Password123",
                   "security_question": "first_school", "security_answer": "Green Valley"}
        response = self.post("/api/signup", payload)
        self.assertEqual(response.status_code, 200, response.get_json())
        self.security_answers = payload
        response = self.post("/api/login", {"username": "test_user", "password": "Password123"})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.csrf = response.get_json()["csrf_token"]

    def test_auth_and_recovery(self):
        self.assertEqual(self.client.get("/api/dashboard").status_code, 401)
        self.signup_and_login()
        duplicate = self.post("/api/signup", {**self.security_answers, "username": "TEST_USER"})
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(self.post("/api/logout", {}).status_code, 200)
        self.csrf = self.client.get("/api/session").get_json()["csrf_token"]
        recovery = {key: value for key, value in self.security_answers.items() if key.startswith("security_")}
        recovery.update(username="test_user", new_password="NewPassword123", confirm_password="NewPassword123")
        wrong = {**recovery, "security_answer": "Not the right answer"}
        self.assertEqual(self.post("/api/forgot-password", wrong).status_code, 400)
        recovery["security_answer"] = "green valley"
        self.assertEqual(self.post("/api/forgot-password", recovery).status_code, 200)
        self.assertEqual(self.post("/api/login", {"username": "test_user", "password": "NewPassword123"}).status_code, 200)

    def test_security_answer_is_hashed_in_database(self):
        self.signup_and_login()
        with project.db() as con:
            user = con.execute("SELECT * FROM users WHERE username='test_user'").fetchone()
        self.assertEqual(user["security_question"], "first_school")
        self.assertNotEqual(user["security_answer_hash"], "Green Valley")
        self.assertTrue(project.check_password_hash(user["security_answer_hash"], "green valley"))
        self.assertNotIn("recovery_hash", user.keys())
        self.assertNotIn("security_question_2", user.keys())

    def test_existing_account_without_question_can_set_one_after_login(self):
        with project.db() as con:
            con.execute("INSERT INTO users (full_name, username, password_hash) VALUES (?, ?, ?)",
                        ("Older User", "older_user", project.generate_password_hash("OldPassword123")))
        login = self.post("/api/login", {"username": "older_user", "password": "OldPassword123"})
        self.assertEqual(login.status_code, 200)
        self.assertFalse(login.get_json()["security_question_set"])
        self.csrf = login.get_json()["csrf_token"]
        setup = self.post("/api/security-question", {"security_question": "first_school", "security_answer": "Green Valley"})
        self.assertEqual(setup.status_code, 200, setup.get_json())
        reset = self.post("/api/forgot-password", {"username": "older_user", "security_question": "first_school",
                            "security_answer": "green valley", "new_password": "NewPassword123",
                            "confirm_password": "NewPassword123"})
        self.assertEqual(reset.status_code, 200, reset.get_json())

    def test_two_question_accounts_migrate_to_first_question(self):
        legacy_path = Path(self.temp.name) / "legacy.db"
        with sqlite3.connect(legacy_path) as con:
            con.execute("""CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT, full_name TEXT NOT NULL,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE, password_hash TEXT NOT NULL,
                recovery_hash TEXT NOT NULL, security_question_1 TEXT, security_answer_1_hash TEXT,
                security_question_2 TEXT, security_answer_2_hash TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
            con.execute("""INSERT INTO users (full_name, username, password_hash, recovery_hash, security_question_1,
                         security_answer_1_hash, security_question_2, security_answer_2_hash)
                         VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        ("Legacy User", "legacy_user", project.generate_password_hash("OldPassword123"),
                         project.generate_password_hash("OldRecoveryCode"), "birth_city",
                         project.generate_password_hash(project.normalize_security_answer("Ahmedabad")), "first_pet",
                         project.generate_password_hash(project.normalize_security_answer("Milo"))))
        original_path = project.app.config["DATABASE"]
        project.app.config["DATABASE"] = str(legacy_path)
        try:
            project.init_db()
            with project.db() as con:
                columns = {row[1] for row in con.execute("PRAGMA table_info(users)")}
            self.assertIn("security_question", columns)
            self.assertNotIn("recovery_hash", columns)
            self.assertNotIn("security_question_2", columns)
            response = self.post("/api/forgot-password", {"username": "legacy_user", "security_question": "birth_city", "security_answer": "Ahmedabad",
                                  "new_password": "NewLegacyPassword123", "confirm_password": "NewLegacyPassword123"})
            self.assertEqual(response.status_code, 200, response.get_json())
        finally:
            project.app.config["DATABASE"] = original_path

    def test_dashboard_filters_paging_and_export(self):
        self.signup_and_login()
        filters = self.client.get("/api/filters").get_json()
        self.assertEqual(project.DATA["Year"].unique().tolist(), [2024])
        self.assertEqual(len(filters["villages"]), 3500)
        overview = self.client.get("/api/dashboard?year=2024").get_json()
        self.assertEqual(overview["kpis"]["villages"], 3500)
        self.assertGreater(overview["kpis"]["population"], 0)
        expected_talukas = project.DATA.groupby("Taluka")["Population_Total"].sum().sort_values(ascending=False)
        self.assertEqual(overview["population_by_taluka"][0]["label"], expected_talukas.index[0])
        taluka = expected_talukas.index[0]
        scoped = self.client.get("/api/dashboard?taluka=" + taluka).get_json()
        self.assertEqual(len(scoped["top_villages"]), 10)
        self.assertTrue(all(row["taluka"] == taluka for row in scoped["top_villages"]))
        sample = filters["villages"][0]
        page = self.client.get("/api/villages?year=2024&village=" + sample).get_json()
        self.assertEqual(page["total"], 1)
        self.assertEqual(page["rows"][0]["Village_Name"], sample)
        paged = self.client.get("/api/villages?per_page=25&page=2").get_json()
        self.assertEqual(len(paged["rows"]), 25)
        self.assertEqual(paged["page"], 2)
        self.assertEqual(self.client.get("/api/villages?page=nope").status_code, 400)
        response = self.client.get("/api/export?year=2024&taluka=" + filters["talukas"][0])
        rows = list(csv.DictReader(io.StringIO(response.get_data(as_text=True))))
        expected = len(project.DATA[project.DATA["Taluka"] == filters["talukas"][0]])
        self.assertEqual(len(rows), expected)
        self.assertEqual(len(rows[0]), 60)

    def test_crop_filter_only_changes_agriculture_and_employment(self):
        self.signup_and_login()
        crop = project.DATA["Main_Crop"].dropna().iloc[0]
        full = self.client.get("/api/dashboard?year=2024").get_json()
        scoped = self.client.get(f"/api/dashboard?year=2024&crop={crop}").get_json()

        # Crop is a subject filter, not a demographic or infrastructure filter.
        self.assertEqual(scoped["kpis"], full["kpis"])
        self.assertEqual(scoped["population_by_taluka"], full["population_by_taluka"])
        self.assertEqual(scoped["households_by_taluka"], full["households_by_taluka"])
        self.assertEqual(scoped["gender_literacy_by_taluka"], full["gender_literacy_by_taluka"])
        self.assertEqual(scoped["services"], full["services"])
        self.assertEqual(scoped["age"], full["age"])
        self.assertLess(scoped["agriculture_kpis"]["villages"], full["agriculture_kpis"]["villages"])
        self.assertLess(scoped["agriculture_kpis"]["area"], full["agriculture_kpis"]["area"])
        self.assertLess(scoped["agriculture_kpis"]["workers"], full["agriculture_kpis"]["workers"])
        self.assertNotEqual(scoped["agriculture_kpis"]["women_workforce"], full["agriculture_kpis"]["women_workforce"])
        self.assertEqual({item["label"] for item in scoped["crop_area"]}, {crop})
        self.assertLess(sum(item["value"] for item in scoped["workforce"]), sum(item["value"] for item in full["workforce"]))

        taluka = project.DATA["Taluka"].dropna().iloc[0]
        options = self.client.get(f"/api/filters?taluka={taluka}").get_json()["villages"]
        self.assertTrue(options)
        self.assertTrue((project.DATA[project.DATA["Village_Name"].isin(options)]["Taluka"] == taluka).all())

    def test_csrf_and_invalid_credentials(self):
        bad = self.client.post("/api/signup", json={"full_name": "Valid Name", "username": "validid", "password": "Password123", "confirm_password": "Password123"})
        self.assertEqual(bad.status_code, 400)
        response = self.post("/api/login", {"username": "missing", "password": "wrong"})
        self.assertEqual(response.status_code, 401)
        for _ in range(5):
            response = self.post("/api/login", {"username": "blocked-user", "password": "wrong"})
            self.assertEqual(response.status_code, 401)
        self.assertEqual(self.post("/api/login", {"username": "blocked-user", "password": "wrong"}).status_code, 429)

    def test_guest_removed_and_data_dictionary_requires_login(self):
        self.assertEqual(self.client.post("/api/guest").status_code, 404)
        self.assertEqual(self.client.get("/api/dashboard").status_code, 401)
        self.signup_and_login()
        dictionary = self.client.get("/api/data-dictionary.csv")
        self.assertEqual(dictionary.status_code, 200)
        self.assertEqual(dictionary.mimetype, "text/csv")
        self.assertIn("Latitude_Illustrative_Not_Official", dictionary.get_data(as_text=True))

    def test_pages_and_static_assets(self):
        home = self.client.get("/")
        self.assertEqual(home.status_code, 200)
        self.assertIn(b"Simulated", home.data)
        self.assertNotIn(b"Explore as a guest", home.data)
        self.assertNotIn(b"Guest preview", home.data)
        self.assertIn(b"Security question", home.data)
        self.assertNotIn(b"recovery code", home.data.lower())
        css = self.client.get("/static/styles.css")
        accessible_css = self.client.get("/static/accessibility.css")
        js = self.client.get("/static/app.js")
        self.assertEqual(css.status_code, 200)
        self.assertEqual(accessible_css.status_code, 200)
        self.assertEqual(js.status_code, 200)
        css.close()
        accessible_css.close()
        js.close()


if __name__ == "__main__":
    unittest.main()
