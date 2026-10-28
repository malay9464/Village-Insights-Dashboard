"""Sabarkantha Village Insights: local Flask app for a synthetic 2024 dataset."""
from __future__ import annotations

import csv
import io
import os
import re
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from functools import wraps
from pathlib import Path

import numpy as np
import pandas as pd
from flask import Flask, Response, jsonify, render_template, request, session
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"
DATA_FILE = BASE_DIR / "sabarkantha_synthetic_visualization_2024_3500_records (2).xlsx"
INSTANCE_DIR.mkdir(exist_ok=True)

SECURITY_QUESTIONS = {
    "first_school": "What was the name of your first school?",
    "childhood_friend": "What was the first name of your childhood best friend?",
    "first_pet": "What was the name of your first pet?",
    "birth_city": "In what city were you born?",
    "favorite_teacher": "What was the surname of a favorite teacher?",
    "childhood_street": "What was the name of the street where you grew up?",
}


def normalize_security_answer(value):
    return " ".join(str(value or "").strip().casefold().split())


def persistent_secret():
    """Create a local secret once; keep sessions valid across app restarts."""
    secret_path = INSTANCE_DIR / "secret_key"
    if not secret_path.exists():
        secret_path.write_text(secrets.token_hex(32), encoding="utf-8")
    return secret_path.read_text(encoding="utf-8").strip()


app = Flask(__name__, instance_path=str(INSTANCE_DIR))
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY") or persistent_secret(),
    DATABASE=os.environ.get("DATABASE_PATH", str(INSTANCE_DIR / "users.db")),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "0") == "1",
    PERMANENT_SESSION_LIFETIME=60 * 60 * 8,
)


@contextmanager
def db():
    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(app.config["DATABASE"])
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def init_db():
    with db() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            username TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            security_question TEXT,
            security_answer_hash TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        columns = {row[1] for row in con.execute("PRAGMA table_info(users)")}
        legacy_columns = {"recovery_hash", "security_question_1", "security_answer_1_hash", "security_question_2", "security_answer_2_hash"}
        if not {"security_question", "security_answer_hash"}.issubset(columns) or columns.intersection(legacy_columns):
            con.execute("ALTER TABLE users RENAME TO users_before_single_question_migration")
            con.execute("""CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                security_question TEXT,
                security_answer_hash TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            old_columns = {row[1] for row in con.execute("PRAGMA table_info(users_before_single_question_migration)")}
            old_rows = con.execute("SELECT * FROM users_before_single_question_migration").fetchall()
            for old in old_rows:
                question = old["security_question"] if "security_question" in old_columns else old["security_question_1"] if "security_question_1" in old_columns else None
                answer_hash = old["security_answer_hash"] if "security_answer_hash" in old_columns else old["security_answer_1_hash"] if "security_answer_1_hash" in old_columns else None
                con.execute("""INSERT INTO users (id, full_name, username, password_hash, security_question, security_answer_hash, created_at)
                             VALUES (?, ?, ?, ?, ?, ?, ?)""",
                            (old["id"], old["full_name"], old["username"], old["password_hash"], question, answer_hash, old["created_at"]))
            con.execute("DROP TABLE users_before_single_question_migration")
        con.execute("""CREATE TABLE IF NOT EXISTS auth_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            username TEXT NOT NULL,
            client_ip TEXT NOT NULL,
            attempted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        con.execute("CREATE INDEX IF NOT EXISTS idx_auth_attempts_lookup ON auth_attempts(action, username, client_ip, attempted_at)")


def load_workbook():
    if not DATA_FILE.is_file():
        raise FileNotFoundError(f"Place the revised workbook beside app.py: {DATA_FILE}")
    with pd.ExcelFile(DATA_FILE) as xls:
        sheets = list(xls.sheet_names)
        data_sheet = "Village_Data" if "Village_Data" in sheets else sheets[0]
        data = pd.read_excel(xls, sheet_name=data_sheet)
        dictionary = pd.read_excel(xls, sheet_name="Data_Dictionary") if "Data_Dictionary" in sheets else None
    data.columns = [str(c).strip() for c in data.columns]
    for col in data.select_dtypes(include="number"):
        data[col] = pd.to_numeric(data[col], errors="coerce")
    return data, dictionary, data_sheet, sheets


DATA, SOURCE_DICTIONARY, DATA_SHEET, WORKBOOK_SHEETS = load_workbook()
init_db()


def field_category(field):
    name = field.lower()
    if any(x in name for x in ("latitude", "longitude", "distance", "area_sqkm")):
        return "Location & area"
    if any(x in name for x in ("crop", "irrigat", "rainfall", "soil", "productivity", "agricultural")):
        return "Agriculture"
    if any(x in name for x in ("literacy", "school", "education", "attendance")):
        return "Education"
    if any(x in name for x in ("health", "maternal")):
        return "Health"
    if any(x in name for x in ("household", "poverty", "lpg", "electricity", "water", "toilet", "internet", "mobile")):
        return "Households & utilities"
    if any(x in name for x in ("worker", "cultivator", "labour", "industry")):
        return "Employment"
    if any(x in name for x in ("population", "sex_ratio", "sc_population", "st_population")):
        return "Population"
    if any(x in name for x in ("available", "connected", "market", "transport", "solar", "road", "bank", "waste")):
        return "Village facilities"
    return "Record details"


FIELD_CATEGORIES = {col: field_category(col) for col in DATA.columns}


def field_unit(field):
    n = field.lower()
    if "percent" in n or "share_percent" in n:
        return "%"
    if "per_1000" in n:
        return "per 1,000 people"
    if "sqkm" in n:
        return "sq km"
    if "rainfall" in n:
        return "mm/year"
    if "_km" in n:
        return "km"
    if "latitude" in n or "longitude" in n:
        return "illustrative decimal degrees"
    if any(n.endswith(s) for s in ("_available", "_connected")):
        return "binary flag (0=no, 1=yes)"
    if n in ("year",):
        return "calendar year"
    if any(s in n for s in ("population", "households", "workers", "cultivators", "labourers", "workers", "_id")):
        return "people / count"
    return "category / text"


def dictionary_frame():
    if SOURCE_DICTIONARY is not None:
        return SOURCE_DICTIONARY.copy()
    rows = []
    for col in DATA.columns:
        sample = DATA[col].dropna()
        rows.append({
            "Field": col,
            "Description": re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", col.replace("_", " ")).strip(),
            "Category": FIELD_CATEGORIES[col],
            "Unit / encoding": field_unit(col),
            "Data type": str(DATA[col].dtype),
            "Missing values": int(DATA[col].isna().sum()),
            "Example": str(sample.iloc[0]) if len(sample) else "",
        })
    return pd.DataFrame(rows)


DATA_DICTIONARY = dictionary_frame()


def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return jsonify(error="Please log in to continue."), 401
        return fn(*args, **kwargs)
    return wrapped


def csrf_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        supplied = request.headers.get("X-CSRF-Token", "")
        expected = session.get("csrf_token", "")
        if not expected or not secrets.compare_digest(supplied, expected):
            return jsonify(error="Your session token expired. Refresh the page and try again."), 400
        return fn(*args, **kwargs)
    return wrapped


def auth_key(value):
    return str(value or "").strip().casefold()[:64]


def is_limited(action, username):
    with db() as con:
        count = con.execute("""SELECT COUNT(*) FROM auth_attempts
            WHERE action=? AND username=? AND client_ip=?
            AND attempted_at >= datetime('now', '-15 minutes')""",
            (action, auth_key(username), request.remote_addr or "unknown")).fetchone()[0]
    return count >= 5


def record_auth_failure(action, username):
    with db() as con:
        con.execute("INSERT INTO auth_attempts(action, username, client_ip) VALUES (?, ?, ?)",
                    (action, auth_key(username), request.remote_addr or "unknown"))
        con.execute("DELETE FROM auth_attempts WHERE attempted_at < datetime('now', '-1 day')")


def clear_auth_failures(action, username):
    with db() as con:
        con.execute("DELETE FROM auth_attempts WHERE action=? AND username=? AND client_ip=?",
                    (action, auth_key(username), request.remote_addr or "unknown"))


def filtered_data(*, include_search=False, include_crop=True):
    df = DATA
    filters = [("year", "Year"), ("taluka", "Taluka"), ("village", "Village_Name")]
    if include_crop:
        filters.append(("crop", "Main_Crop"))
    for key, column in filters:
        value = request.args.get(key, "All").strip()
        if value and value != "All" and column in df:
            df = df[df[column].astype(str) == value]
    term = request.args.get("search", "").strip().casefold() if include_search else ""
    if term:
        searchable = [c for c in ("Village_Name", "Taluka") if c in df]
        mask = pd.Series(False, index=df.index)
        for col in searchable:
            mask |= df[col].astype(str).str.casefold().str.contains(term, regex=False, na=False)
        df = df[mask]
    return df


def dedup_villages(df):
    if "Village_Name" not in df:
        return df.copy()
    keys = [c for c in ("Year", "Village_Name") if c in df]
    return df.sort_values("Record_ID" if "Record_ID" in df else keys, kind="stable").drop_duplicates(keys, keep="first")


def number_sum(df, col):
    return float(pd.to_numeric(df[col], errors="coerce").sum()) if col in df else 0.0


def number_mean(df, col):
    vals = pd.to_numeric(df[col], errors="coerce").dropna() if col in df else pd.Series(dtype=float)
    return float(vals.mean()) if len(vals) else 0.0


def availability_pct(df, col):
    vals = pd.to_numeric(df[col], errors="coerce").dropna() if col in df else pd.Series(dtype=float)
    return round(float((vals > 0).mean() * 100), 1) if len(vals) else 0.0


def grouped(df, key, field, *, mean=False, ascending=False, limit=None):
    if df.empty or key not in df or field not in df:
        return []
    grouped_values = df.groupby(key, dropna=False)[field].mean() if mean else df.groupby(key, dropna=False)[field].sum()
    grouped_values = grouped_values.sort_values(ascending=ascending, kind="stable")
    if limit is not None:
        grouped_values = grouped_values.head(limit)
    return [{"label": str(k) if pd.notna(k) else "Unknown", "value": round(float(v), 2)} for k, v in grouped_values.items() if pd.notna(v)]


def category_counts(df, field):
    if df.empty or field not in df:
        return []
    values = df[field].fillna("Unknown").astype(str).value_counts().sort_values(ascending=False, kind="stable")
    return [{"label": str(k), "value": int(v)} for k, v in values.items()]


UTILITY_FIELDS = [
    ("Electricity", "Households_Electricity_Percent"),
    ("Piped water", "Households_Piped_Water_Percent"),
    ("Toilet access", "Households_Toilet_Percent"),
    ("Internet", "Households_Internet_Percent"),
    ("Mobile access", "Households_Mobile_Access_Percent"),
    ("LPG", "Households_LPG_Percent"),
]
FACILITY_FIELDS = [
    ("Primary school", "Primary_School_Available"),
    ("Secondary school", "Secondary_School_Available"),
    ("Health facility", "Health_Facility_Available"),
    ("Bank", "Bank_Available"),
    ("Weekly market", "Weekly_Market_Available"),
    ("All-weather road", "All_Weather_Road_Connected"),
    ("Solar", "Solar_Energy_Available"),
    ("Waste collection", "Waste_Collection_Available"),
    ("Public transport", "Public_Transport_Available"),
    ("Community water tank", "Community_Water_Tank_Available"),
]


def dashboard_payload(demo_raw, agri_raw):
    demo, agriculture = dedup_villages(demo_raw), dedup_villages(agri_raw)
    if "Village_Name" in demo:
        village_count = int(demo["Village_Name"].nunique())
    else:
        village_count = len(demo)
    total_pop = number_sum(demo, "Population_Total")
    male_literacy = number_mean(demo, "Male_Literacy_Rate_Percent")
    female_literacy = number_mean(demo, "Female_Literacy_Rate_Percent")
    internet = number_mean(demo, "Households_Internet_Percent")
    mobile = number_mean(demo, "Households_Mobile_Access_Percent")
    men, women = number_sum(demo, "Population_Male"), number_sum(demo, "Population_Female")

    taluka = demo.groupby("Taluka", dropna=False) if "Taluka" in demo else None
    by_taluka = []
    if taluka is not None:
        for name, group in taluka:
            by_taluka.append({
                "label": str(name),
                "population": int(number_sum(group, "Population_Total")),
                "households": int(number_sum(group, "Households")),
                "male_literacy": round(number_mean(group, "Male_Literacy_Rate_Percent"), 1),
                "female_literacy": round(number_mean(group, "Female_Literacy_Rate_Percent"), 1),
                "literacy_gap": round(number_mean(group.assign(_gap=group["Male_Literacy_Rate_Percent"] - group["Female_Literacy_Rate_Percent"]), "_gap"), 1),
                "child_attendance": round(number_mean(group, "Child_School_Attendance_Percent"), 1),
                "maternal_access": round(number_mean(group, "Maternal_Health_Access_Percent"), 1),
                "poverty": round(number_mean(group, "Household_Poverty_Rate_Percent"), 1),
                "taluka_distance": round(number_mean(group, "Distance_to_Taluka_Center_Km"), 1),
                "district_distance": round(number_mean(group, "Distance_to_District_Center_Km"), 1),
                "facilities": {label: availability_pct(group, field) for label, field in FACILITY_FIELDS if field in group},
            })
    by_taluka.sort(key=lambda item: item["population"], reverse=True)

    pop = pd.to_numeric(demo.get("Population_Total", pd.Series(dtype=float)), errors="coerce").dropna()
    bins = [0, 250, 500, 1000, 1500, 2500, 5000, 10000, float("inf")]
    labels = ["1–250", "251–500", "501–1,000", "1,001–1,500", "1,501–2,500", "2,501–5,000", "5,001–10,000", "10,001+"]
    size_counts = pd.cut(pop, bins=bins, labels=labels, include_lowest=True).value_counts(sort=False)

    utility = [{"label": label, "value": round(number_mean(demo, field), 1)} for label, field in UTILITY_FIELDS if field in demo]
    facility_heatmap = [{"taluka": row["label"], **row["facilities"]} for row in by_taluka]
    gender_by_taluka = [{"label": row["label"], "male": row["male_literacy"], "female": row["female_literacy"], "gap": row["literacy_gap"]} for row in by_taluka]
    age = [{"label": label, "value": int(number_sum(demo, field))} for label, field in (
        ("0–14 years", "Population_Age_0_14"), ("15–59 years", "Population_Age_15_59"), ("60+ years", "Population_Age_60_Plus"))]
    denominator = total_pop or 1

    def ranked(frame, largest):
        ordered = frame.sort_values("Population_Total", ascending=not largest, kind="stable").head(10)
        return [{"village": str(row.Village_Name), "taluka": str(row.Taluka), "value": int(row.Population_Total)} for row in ordered.itertuples()]

    services = [{"label": label, "value": availability_pct(demo, col)} for label, col in (
        ("Health facility", "Health_Facility_Available"), ("Bank", "Bank_Available"), ("Solar", "Solar_Energy_Available")) if col in demo]
    crops = grouped(agriculture, "Main_Crop", "Agricultural_Area_SqKm", limit=None)
    irrigation = grouped(agriculture, "Primary_Irrigation_Source", "Agricultural_Area_SqKm")
    soil = category_counts(agriculture, "Predominant_Soil_Type")
    workers = [{"label": label, "value": int(number_sum(agriculture, col))} for label, col in (
        ("Cultivators", "Cultivators"), ("Agricultural labourers", "Agricultural_Labourers"),
        ("Household industry", "Household_Industry_Workers"), ("Other workers", "Other_Workers"))]

    return {
        "year": sorted(pd.to_numeric(demo["Year"], errors="coerce").dropna().astype(int).unique().tolist()) if "Year" in demo else [],
        "kpis": {
            "population": int(round(total_pop)), "villages": village_count,
            "households": int(round(number_sum(demo, "Households"))),
            "literacy": round(number_mean(demo, "Literacy_Rate_Percent"), 1),
            "male_literacy": round(male_literacy, 1), "female_literacy": round(female_literacy, 1),
            "literacy_gap": round(male_literacy - female_literacy, 1),
            "internet": round(internet, 1), "mobile": round(mobile, 1), "digital_gap": round(mobile - internet, 1),
            "health_facility": availability_pct(demo, "Health_Facility_Available"),
            "bank": availability_pct(demo, "Bank_Available"), "solar": availability_pct(demo, "Solar_Energy_Available"),
            "household_size": round(number_mean(demo, "Average_Household_Size"), 1),
            "sex_ratio": round(women / men * 1000, 1) if men else 0,
            "sc_share": round(number_sum(demo, "SC_Population") / denominator * 100, 1),
            "st_share": round(number_sum(demo, "ST_Population") / denominator * 100, 1),
            "median_population": int(pop.median()) if len(pop) else 0,
            "largest_population": int(pop.max()) if len(pop) else 0,
            "poverty": round(number_mean(demo, "Household_Poverty_Rate_Percent"), 1),
            "school_attendance": round(number_mean(demo, "Child_School_Attendance_Percent"), 1),
            "maternal_access": round(number_mean(demo, "Maternal_Health_Access_Percent"), 1),
        },
        "agriculture_kpis": {
            "villages": int(agriculture["Village_Name"].nunique()) if "Village_Name" in agriculture else len(agriculture),
            "area": round(number_sum(agriculture, "Agricultural_Area_SqKm"), 1),
            "rainfall": round(number_mean(agriculture, "Estimated_Annual_Rainfall_mm"), 1),
            "workers": int(number_sum(agriculture, "Total_Workers")),
            "women_workforce": round(number_mean(agriculture, "Women_Workforce_Participation_Percent"), 1),
        },
        "population_by_taluka": [{"label": r["label"], "value": r["population"]} for r in by_taluka],
        "households_by_taluka": [{"label": r["label"], "value": r["households"]} for r in by_taluka],
        "gender_literacy_by_taluka": gender_by_taluka,
        "education_by_taluka": [{"label": r["label"], "attendance": r["child_attendance"], "maternal": r["maternal_access"]} for r in by_taluka],
        "poverty_by_taluka": [{"label": r["label"], "value": r["poverty"]} for r in by_taluka],
        "distance_by_taluka": [{"label": r["label"], "taluka_km": r["taluka_distance"], "district_km": r["district_distance"]} for r in by_taluka],
        "facility_heatmap": facility_heatmap,
        "utilities": utility,
        "services": services,
        "age": age,
        "population_size": [{"label": str(k), "value": int(v)} for k, v in size_counts.items()],
        "top_villages": ranked(demo, True), "bottom_villages": ranked(demo, False),
        "crop_area": crops, "irrigation": irrigation, "soil": soil, "workforce": workers,
    }


@app.get("/")
def home():
    categories = sorted(set(FIELD_CATEGORIES.values()))
    return render_template("index.html", security_questions=SECURITY_QUESTIONS, metadata={
        "records": len(DATA), "fields": len(DATA.columns), "categories": len(categories),
        "year": int(DATA["Year"].dropna().max()) if "Year" in DATA and DATA["Year"].notna().any() else "—",
    })


@app.get("/api/session")
def api_session():
    if session.get("guest") and not session.get("user_id"):
        session.clear()
    session.setdefault("csrf_token", secrets.token_urlsafe(32))
    active = bool(session.get("user_id"))
    question_set = False
    if active:
        with db() as con:
            user = con.execute("SELECT security_question, security_answer_hash FROM users WHERE id = ?", (session["user_id"],)).fetchone()
        question_set = bool(user and user["security_question"] and user["security_answer_hash"])
    return jsonify(
        authenticated=active,
        user=session.get("full_name"),
        username=session.get("username"),
        security_question_set=question_set,
        csrf_token=session["csrf_token"],
    )


@app.post("/api/signup")
@csrf_required
def signup():
    data = request.get_json(silent=True) or {}
    name, username = str(data.get("full_name", "")).strip(), str(data.get("username", "")).strip()
    password, confirm = str(data.get("password", "")), str(data.get("confirm_password", ""))
    question = str(data.get("security_question", ""))
    answer = normalize_security_answer(data.get("security_answer"))
    if len(name) < 2 or len(name) > 80:
        return jsonify(error="Name must be between 2 and 80 characters.", field="full_name"), 400
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,24}", username):
        return jsonify(error="Login ID must be 3–24 characters using letters, numbers, dot, underscore or hyphen.", field="username"), 400
    if len(password) < 8 or len(password) > 128:
        return jsonify(error="Password must contain 8–128 characters.", field="password"), 400
    if password != confirm:
        return jsonify(error="Passwords do not match.", field="confirm_password"), 400
    if question not in SECURITY_QUESTIONS:
        return jsonify(error="Choose a security question.", field="security_question"), 400
    if not 2 <= len(answer) <= 160:
        return jsonify(error="Answer must contain 2–160 characters.", field="security_answer"), 400
    try:
        with db() as con:
            con.execute("INSERT INTO users (full_name, username, password_hash, security_question, security_answer_hash) VALUES (?, ?, ?, ?, ?)",
                        (name, username, generate_password_hash(password), question, generate_password_hash(answer)))
    except sqlite3.IntegrityError:
        return jsonify(error="That Login ID is already taken. Choose another.", field="username"), 409
    return jsonify(message="Account created. You can now sign in with your Login ID and password.")


@app.post("/api/login")
@csrf_required
def login():
    data = request.get_json(silent=True) or {}
    username, password = str(data.get("username", "")).strip(), str(data.get("password", ""))
    if is_limited("login", username):
        return jsonify(error="Too many failed sign-in attempts. Wait 15 minutes and try again."), 429
    with db() as con:
        user = con.execute("SELECT * FROM users WHERE username = ? COLLATE NOCASE", (username,)).fetchone()
    if not user or not check_password_hash(user["password_hash"], password):
        record_auth_failure("login", username)
        return jsonify(error="Incorrect Login ID or password.", field="password"), 401
    clear_auth_failures("login", username)
    session.clear()
    session.permanent = True
    session.update(user_id=user["id"], full_name=user["full_name"], username=user["username"], csrf_token=secrets.token_urlsafe(32))
    return jsonify(message="Welcome back.", user=user["full_name"], username=user["username"],
                   security_question_set=bool(user["security_question"] and user["security_answer_hash"]), csrf_token=session["csrf_token"])


@app.post("/api/security-question")
@login_required
@csrf_required
def set_security_question():
    data = request.get_json(silent=True) or {}
    question = str(data.get("security_question", ""))
    answer = normalize_security_answer(data.get("security_answer"))
    if question not in SECURITY_QUESTIONS:
        return jsonify(error="Choose a security question.", field="security_question"), 400
    if not 2 <= len(answer) <= 160:
        return jsonify(error="Answer must contain 2–160 characters.", field="security_answer"), 400
    with db() as con:
        con.execute("UPDATE users SET security_question = ?, security_answer_hash = ? WHERE id = ?",
                    (question, generate_password_hash(answer), session["user_id"]))
    return jsonify(message="Security question saved. You can now reset your password with this answer.")


@app.post("/api/forgot-password")
@csrf_required
def forgot_password():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    question = str(data.get("security_question", ""))
    answer = normalize_security_answer(data.get("security_answer"))
    password, confirm = str(data.get("new_password", "")), str(data.get("confirm_password", ""))
    if len(password) < 8 or len(password) > 128:
        return jsonify(error="New password must contain 8–128 characters.", field="new_password"), 400
    if password != confirm:
        return jsonify(error="Passwords do not match.", field="confirm_password"), 400
    if is_limited("recovery", username):
        return jsonify(error="Too many recovery attempts. Wait 15 minutes and try again."), 429
    with db() as con:
        user = con.execute("SELECT * FROM users WHERE username = ? COLLATE NOCASE", (username,)).fetchone()
    if not user or not user["security_question"] or not user["security_answer_hash"]:
        record_auth_failure("recovery", username)
        return jsonify(error="Login ID or security answers are incorrect.", field="username"), 400
    answers_match = question == user["security_question"] and bool(answer) and check_password_hash(user["security_answer_hash"], answer)
    if not answers_match:
        record_auth_failure("recovery", username)
        return jsonify(error="Login ID or security answer is incorrect.", field="security_answer"), 400
    with db() as con:
        con.execute("UPDATE users SET password_hash = ? WHERE id = ?", (generate_password_hash(password), user["id"]))
    clear_auth_failures("recovery", username)
    clear_auth_failures("login", username)
    return jsonify(message="Password reset successfully. You can now log in.")


@app.post("/api/logout")
@csrf_required
def logout():
    session.clear()
    return jsonify(message="Logged out.")


@app.get("/api/metadata")
def metadata():
    column_metadata = [{
        "key": col,
        "label": re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", col.replace("_", " ")).replace("Percent", " (%)").replace("SqKm", " (sq km)"),
        "category": FIELD_CATEGORIES[col],
        "unit": field_unit(col),
        "dtype": str(DATA[col].dtype),
    } for col in DATA.columns]
    return jsonify(records=len(DATA), fields=len(DATA.columns), categories=len(set(FIELD_CATEGORIES.values())),
                    years=sorted(DATA.Year.dropna().astype(int).unique().tolist()) if "Year" in DATA else [],
                    talukas=int(DATA.Taluka.nunique()) if "Taluka" in DATA else 0,
                    workbook_sheets=WORKBOOK_SHEETS, data_sheet=DATA_SHEET,
                    has_source_dictionary=SOURCE_DICTIONARY is not None,
                    columns=column_metadata)


@app.get("/api/filters")
@login_required
def filters():
    result = {}
    for key, column in (("talukas", "Taluka"), ("crops", "Main_Crop")):
        result[key] = sorted(DATA[column].dropna().astype(str).unique().tolist()) if column in DATA else []
    villages = DATA
    selected_taluka = request.args.get("taluka", "All").strip()
    if selected_taluka != "All" and "Taluka" in villages:
        villages = villages[villages["Taluka"].astype(str) == selected_taluka]
    result["villages"] = sorted(villages.Village_Name.dropna().astype(str).unique().tolist()) if "Village_Name" in DATA else []
    return jsonify(result)


@app.get("/api/dashboard")
@login_required
def dashboard():
    demographics = filtered_data(include_crop=False)
    agriculture = filtered_data(include_crop=True)
    return jsonify(dashboard_payload(demographics, agriculture))


DEFAULT_TABLE_COLUMNS = ["Village_Name", "Taluka", "Population_Total", "Households", "Literacy_Rate_Percent", "Households_Internet_Percent", "Main_Crop", "Health_Facility_Available", "Household_Poverty_Rate_Percent", "Year"]


@app.get("/api/villages")
@login_required
def villages():
    df = dedup_villages(filtered_data(include_search=True, include_crop=True))
    total = len(df)
    allowed = set(DATA.columns)
    sort = request.args.get("sort", "Village_Name")
    if sort not in allowed:
        sort = "Village_Name"
    direction = request.args.get("direction", "asc").lower()
    df = df.sort_values(sort, ascending=(direction != "desc"), na_position="last", kind="stable")
    try:
        page = max(1, int(request.args.get("page", 1) or 1))
        per_page = max(10, min(int(request.args.get("per_page", 25) or 25), 100))
    except (TypeError, ValueError):
        return jsonify(error="Page and page size must be integers."), 400
    requested = [c for c in request.args.get("columns", "").split(",") if c in allowed]
    columns = list(dict.fromkeys(requested)) if requested else [c for c in DEFAULT_TABLE_COLUMNS if c in allowed]
    page_df = df.iloc[(page - 1) * per_page:page * per_page][columns]
    display_columns = [{"key": c, "label": c.replace("_", " ").replace("Percent", " (%)").replace("SqKm", " (sq km)")} for c in columns]
    rows = page_df.astype(object).where(pd.notna(page_df), None).to_dict(orient="records")
    return jsonify(rows=rows, columns=display_columns, total=int(total), page=page, per_page=per_page,
                   pages=max(1, (total + per_page - 1) // per_page))


@app.get("/api/export")
@login_required
def export():
    df = dedup_villages(filtered_data(include_search=True, include_crop=True))
    columns = [c for c in request.args.get("columns", "").split(",") if c in DATA.columns]
    if columns:
        df = df[columns]
    content = df.to_csv(index=False, quoting=csv.QUOTE_MINIMAL)
    return Response("\ufeff" + content, mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=sabarkantha_filtered_data.csv"})


@app.get("/api/data-dictionary.csv")
@login_required
def data_dictionary():
    content = DATA_DICTIONARY.to_csv(index=False, quoting=csv.QUOTE_MINIMAL)
    return Response("\ufeff" + content, mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=sabarkantha_data_dictionary.csv"})


if __name__ == "__main__":
    app.run(host=os.environ.get("HOST", "0.0.0.0"), port=int(os.environ.get("PORT", 5000)), debug=False)
