"""Sabarkantha Village Insights: Flask API and data aggregation layer."""
from __future__ import annotations

import os
import re
import secrets
import sqlite3
from functools import wraps
from pathlib import Path

import pandas as pd
from flask import Flask, Response, jsonify, request, session, render_template
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "sabarkantha_synthetic_visualization_2024_3500_records.xlsx"
app = Flask(__name__, instance_path=str(BASE_DIR / "instance"))
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY", "local-demo-key-change-before-deployment"),
    DATABASE=os.environ.get("DATABASE_PATH", str(BASE_DIR / "instance" / "users.db")),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "0") == "1",
    PERMANENT_SESSION_LIFETIME=60 * 60 * 8,
)


def db():
    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(app.config["DATABASE"])
    con.row_factory = sqlite3.Row
    return con


def init_db():
    with db() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            username TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            recovery_hash TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")


def load_data():
    if not DATA_FILE.is_file():
        raise FileNotFoundError(f"Place the supplied workbook beside app.py: {DATA_FILE}")
    df = pd.read_excel(DATA_FILE, sheet_name="Village_Data")
    df.columns = [str(c).strip() for c in df.columns]
    for col in df.select_dtypes(include="number"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


DATA = load_data()
init_db()


def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return jsonify(error="Please log in to continue."), 401
        return fn(*args, **kwargs)
    return wrapped


def filtered_data(include_search=True, include_crop=True):
    df = DATA
    filters = [("year", "Year"), ("taluka", "Taluka"), ("village", "Village_Name")]
    if include_crop:
        filters.append(("crop", "Main_Crop"))
    for key, column in filters:
        value = request.args.get(key, "All").strip()
        if value and value != "All" and column in df:
            df = df[df[column].astype(str) == value]
    search = request.args.get("search", "").strip().casefold() if include_search else ""
    if search:
        matches = df.astype(str).apply(lambda col: col.str.casefold().str.contains(search, regex=False, na=False)).any(axis=1)
        df = df[matches]
    return df


def dedup_villages(df):
    if "Village_Name" not in df:
        return df
    keys = [c for c in ("Year", "Village_Name") if c in df]
    return df.sort_values("Record_ID" if "Record_ID" in df else keys).drop_duplicates(keys, keep="first")


def number_sum(df, col):
    return float(pd.to_numeric(df[col], errors="coerce").sum()) if col in df else 0.0


def number_mean(df, col):
    return float(pd.to_numeric(df[col], errors="coerce").mean()) if col in df and df[col].notna().any() else 0.0


def grouped(df, by, value, *, mean=False, limit=None, ascending=False):
    if by not in df or value not in df or df.empty:
        return []
    series = df.groupby(by, dropna=False)[value].mean() if mean else df.groupby(by, dropna=False)[value].sum()
    series = series.sort_values(ascending=ascending)
    if limit:
        series = series.head(limit)
    return [{"label": str(k) if pd.notna(k) else "Unknown", "value": round(float(v), 2)} for k, v in series.items() if pd.notna(v)]


SERVICE_FIELDS = [
    ("Primary school", "Primary_School_Available"),
    ("Secondary school", "Secondary_School_Available"),
    ("Health facility", "Health_Facility_Available"),
    ("Bank", "Bank_Available"),
    ("Weekly market", "Weekly_Market_Available"),
    ("All-weather road", "All_Weather_Road_Connected"),
    ("Electricity", "Households_Electricity_Percent"),
    ("Piped water", "Households_Piped_Water_Percent"),
    ("Toilet access", "Households_Toilet_Percent"),
    ("Internet", "Households_Internet_Percent"),
    ("Public transport", "Public_Transport_Available"),
]


def dashboard_payload(raw, agriculture_raw=None):
    df = dedup_villages(raw)
    agriculture_df = dedup_villages(agriculture_raw if agriculture_raw is not None else raw)
    avg = lambda c: round(number_mean(df, c), 1)
    available = []
    for label, field in SERVICE_FIELDS:
        if field not in df:
            continue
        vals = pd.to_numeric(df[field], errors="coerce").dropna()
        if not len(vals):
            continue
        # Binary availability columns are village shares; coverage fields are already percentages.
        pct = (vals.gt(0).mean() * 100) if vals.max() <= 1 else vals.mean()
        available.append({"label": label, "value": round(float(pct), 1)})
    return {
        "year": sorted(pd.to_numeric(df["Year"], errors="coerce").dropna().unique().astype(int).tolist()) if "Year" in df else [],
        "records": int(len(raw)),
        "kpis": {
            "population": int(round(number_sum(df, "Population_Total"))),
            "villages": int(df["Village_Name"].nunique()) if "Village_Name" in df else len(df),
            "households": int(round(number_sum(df, "Households"))),
            "literacy": avg("Literacy_Rate_Percent"),
            "internet": avg("Households_Internet_Percent"),
            "household_size": avg("Average_Household_Size"),
            "schools": int(sum(number_sum(df, c) for c in ("Primary_School_Available", "Secondary_School_Available"))),
            "health_facilities": int(number_sum(df, "Health_Facility_Available")),
        },
        "agriculture_kpis": {
            "villages": int(agriculture_df["Village_Name"].nunique()) if "Village_Name" in agriculture_df else len(agriculture_df),
            "area": round(number_sum(agriculture_df, "Agricultural_Area_SqKm"), 1),
            "rainfall": round(number_mean(agriculture_df, "Estimated_Annual_Rainfall_mm"), 1),
            "total_workers": int(round(number_sum(agriculture_df, "Total_Workers"))),
            "women_workforce": round(number_mean(agriculture_df, "Women_Workforce_Participation_Percent"), 1),
        },
        "population_by_taluka": grouped(df, "Taluka", "Population_Total", limit=10),
        "households_by_taluka": grouped(df, "Taluka", "Households", limit=10),
        "crop_area": grouped(agriculture_df, "Main_Crop", "Agricultural_Area_SqKm", limit=10),
        "literacy_by_taluka": grouped(df, "Taluka", "Literacy_Rate_Percent", mean=True, ascending=True),
        "irrigation": grouped(agriculture_df, "Primary_Irrigation_Source", "Agricultural_Area_SqKm"),
        "services": available,
        "gender": [{"label": "Male", "value": int(number_sum(df, "Population_Male"))}, {"label": "Female", "value": int(number_sum(df, "Population_Female"))}],
        "age": [{"label": "0–14 years", "value": int(number_sum(df, "Population_Age_0_14"))}, {"label": "15–59 years", "value": int(number_sum(df, "Population_Age_15_59"))}, {"label": "60+ years", "value": int(number_sum(df, "Population_Age_60_Plus"))}],
        "workforce": [{"label": label, "value": int(number_sum(agriculture_df, col))} for label, col in (("Cultivators", "Cultivators"), ("Agricultural labourers", "Agricultural_Labourers"), ("Household industry", "Household_Industry_Workers"), ("Other workers", "Other_Workers"))],
    }


@app.get("/")
def home():
    return render_template("index.html")


@app.get("/api/session")
def api_session():
    session.setdefault("csrf_token", secrets.token_urlsafe(32))
    if not session.get("user_id"):
        return jsonify(authenticated=False, csrf_token=session["csrf_token"])
    return jsonify(authenticated=True, user=session.get("full_name"), username=session.get("username"), csrf_token=session["csrf_token"])


def csrf_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        supplied = request.headers.get("X-CSRF-Token", "")
        expected = session.get("csrf_token", "")
        if not expected or not secrets.compare_digest(supplied, expected):
            return jsonify(error="Your session token expired. Refresh the page and try again."), 400
        return fn(*args, **kwargs)
    return wrapped


@app.post("/api/signup")
@csrf_required
def signup():
    data = request.get_json(silent=True) or {}
    name, username = str(data.get("full_name", "")).strip(), str(data.get("username", "")).strip()
    password, confirm = str(data.get("password", "")), str(data.get("confirm_password", ""))
    recovery = str(data.get("recovery_code", "")).strip()
    if len(name) < 2 or len(name) > 80:
        return jsonify(error="Name must be between 2 and 80 characters."), 400
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,24}", username):
        return jsonify(error="Login ID must be 3–24 characters using letters, numbers, dot, underscore or hyphen."), 400
    if len(password) < 8 or len(password) > 128:
        return jsonify(error="Password must contain 8–128 characters."), 400
    if password != confirm:
        return jsonify(error="Passwords do not match."), 400
    if len(recovery) < 6 or len(recovery) > 128:
        return jsonify(error="Recovery code must contain 6–128 characters. Keep it safe."), 400
    try:
        with db() as con:
            con.execute("INSERT INTO users (full_name, username, password_hash, recovery_hash) VALUES (?, ?, ?, ?)",
                        (name, username, generate_password_hash(password), generate_password_hash(recovery)))
    except sqlite3.IntegrityError:
        return jsonify(error="That Login ID is already taken. Choose another."), 409
    return jsonify(message="Account created. You can now log in with your Login ID.")


@app.post("/api/login")
@csrf_required
def login():
    data = request.get_json(silent=True) or {}
    username, password = str(data.get("username", "")).strip(), str(data.get("password", ""))
    with db() as con:
        user = con.execute("SELECT * FROM users WHERE username = ? COLLATE NOCASE", (username,)).fetchone()
    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify(error="Incorrect Login ID or password."), 401
    session.clear()
    session.permanent = True
    session.update(user_id=user["id"], full_name=user["full_name"], username=user["username"], csrf_token=secrets.token_urlsafe(32))
    return jsonify(message="Welcome back.", user=user["full_name"], username=user["username"], csrf_token=session["csrf_token"])


@app.post("/api/forgot-password")
@csrf_required
def forgot_password():
    data = request.get_json(silent=True) or {}
    username, recovery = str(data.get("username", "")).strip(), str(data.get("recovery_code", "")).strip()
    password = str(data.get("new_password", ""))
    if len(password) < 8 or len(password) > 128:
        return jsonify(error="New password must contain 8–128 characters."), 400
    with db() as con:
        user = con.execute("SELECT * FROM users WHERE username = ? COLLATE NOCASE", (username,)).fetchone()
        if not user or not check_password_hash(user["recovery_hash"], recovery):
            return jsonify(error="Login ID or recovery code is incorrect."), 400
        con.execute("UPDATE users SET password_hash = ? WHERE id = ?", (generate_password_hash(password), user["id"]))
    return jsonify(message="Password reset successfully. You can now log in.")


@app.post("/api/logout")
@csrf_required
def logout():
    session.clear()
    return jsonify(message="Logged out.")


@app.get("/api/filters")
@login_required
def filters():
    options = {"years": ("Year", int), "talukas": ("Taluka", str), "villages": ("Village_Name", str), "crops": ("Main_Crop", str)}
    result = {}
    for key, (column, cast) in options.items():
        source = DATA
        selected_taluka = request.args.get("taluka", "All").strip()
        if key == "villages" and selected_taluka != "All":
            source = source[source["Taluka"].astype(str) == selected_taluka]
        result[key] = sorted(source[column].dropna().map(cast).unique().tolist()) if column in source else []
    return jsonify(result)


@app.get("/api/dashboard")
@login_required
def dashboard():
    demographic_df = filtered_data(include_crop=False)
    agriculture_df = filtered_data()
    return jsonify(dashboard_payload(demographic_df, agriculture_df))


@app.get("/api/villages")
@login_required
def villages():
    df = dedup_villages(filtered_data())
    total = len(df)
    allowed = set(DATA.columns)
    sort = request.args.get("sort", "Village_Name")
    if sort not in allowed:
        sort = "Village_Name"
    direction = request.args.get("direction", "asc").lower()
    df = df.sort_values(sort, ascending=(direction != "desc"), na_position="last", kind="stable")
    try:
        page = max(1, min(int(request.args.get("page", 1) or 1), 100000))
        per_page = max(10, min(int(request.args.get("per_page", 25) or 25), 100))
    except (TypeError, ValueError):
        return jsonify(error="Page and page size must be integers."), 400
    cols = ["Village_Name", "Taluka", "Year", "Population_Total", "Households", "Literacy_Rate_Percent", "Households_Internet_Percent", "Main_Crop", "Health_Facility_Available"]
    cols = [c for c in cols if c in df]
    page_df = df.iloc[(page - 1) * per_page:page * per_page][cols].rename(columns={
        "Village_Name": "Village", "Population_Total": "Population", "Literacy_Rate_Percent": "Literacy (%)",
        "Households_Internet_Percent": "Internet access (%)", "Main_Crop": "Main crop", "Health_Facility_Available": "Health facility"})
    rows = page_df.astype(object).where(pd.notna(page_df), None).to_dict(orient="records")
    return jsonify(rows=rows, total=int(total), page=page, per_page=per_page, pages=max(1, (total + per_page - 1) // per_page))


@app.get("/api/export")
@login_required
def export():
    df = dedup_villages(filtered_data())
    return Response(df.to_csv(index=False), mimetype="text/csv; charset=utf-8", headers={"Content-Disposition": "attachment; filename=sabarkantha_filtered_data.csv"})


if __name__ == "__main__":
    # Bind on all interfaces so VS Code's forwarded-port preview can reach Flask.
    # Set HOST=127.0.0.1 to keep the server limited to this computer.
    app.run(host=os.environ.get("HOST", "0.0.0.0"), port=int(os.environ.get("PORT", 5000)), debug=False)
