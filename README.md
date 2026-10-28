# Sabarkantha Village Insights

A local Flask dashboard for exploring the supplied Sabarkantha synthetic village dataset. The workbook has 3,500 rows and 58 fields and represents a **single 2024 snapshot** across seven talukas. The workbook is synthetic/simulated, not government or census data.

## Run on Windows 11

Run these commands from this project folder:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --default-timeout=300 --retries=10 -r requirements.txt
python app.py
```

Wait for Flask to print its `Running on ...` message, then keep that terminal open and visit <http://127.0.0.1:5000>. The app reads the included Excel workbook beside `app.py` and initializes `instance/users.db` automatically. No dataset generation step is needed because this project uses the workbook you supplied. Chart.js and Google Fonts are loaded from CDNs, so the charts and remote fonts need an internet connection; the rest of the app runs locally.

Flask binds to all network interfaces by default so a VS Code forwarded-port preview can reach it. This is intended for local demos on a trusted network. To restrict access to this computer only, stop the server with `Ctrl+C`, then run `$env:HOST='127.0.0.1'; python app.py` in PowerShell. If VS Code's embedded preview still times out, open the **Ports** panel, forward port `5000`, and open the forwarded address; alternatively open `http://127.0.0.1:5000` in Edge or Chrome on the same computer.

Create an account with a Login ID, password, and recovery code. Keep the recovery code private; it is stored as a password hash and is not shown again. Set a stable random `SECRET_KEY` environment variable before using the app beyond a local demonstration. For HTTPS deployments set `COOKIE_SECURE=1`. This student project does not include production rate limiting or multi-user deployment hardening.

## Features

- Login, registration, logout, and recovery-code password reset, using SQLite and Werkzeug password hashing.
- Session-protected data APIs and CSRF checks for write requests.
- Dashboard filters for year, taluka, village, and crop; reset filters restores the full view.
- Filter scopes are explicit: year/taluka/village affect all insights; crop affects agriculture/employment and row-level explorer results, but not demographic, education, or infrastructure summaries.
- Population, household, education/infrastructure, agriculture, workforce, and service summaries with Chart.js.
- Searchable, sortable, paginated village explorer; CSV exports the complete filtered and searched result, not just the visible page.
- Methodology and About sections explaining the synthetic data limitations.

Totals are calculated after deduplicating on year and village. Rates are arithmetic averages of village-level values; binary service flags are converted to the share of villages reporting availability. Because the provided workbook contains only 2024, the interface explicitly describes it as a snapshot and does not imply historical change. This simulated data is for demonstration only and should not be used for policy or operational decisions.

## Project files

- `app.py` — Flask routes, authentication, filters, aggregation, explorer, and CSV export.
- `templates/index.html` — responsive single-page dashboard and auth screens.
- `static/app.js`, `static/styles.css` — interactions, charts, and responsive styling.
- `sabarkantha_synthetic_visualization_2024_3500_records.xlsx` — supplied workbook.
- `instance/users.db` — created on first run; contains local user accounts.
- `tests/test_app.py` — backend tests for authentication, recovery, aggregation, filters, pagination, CSV export, and CSRF.

## Run backend checks

```powershell
python -m unittest discover -s tests -v
```
