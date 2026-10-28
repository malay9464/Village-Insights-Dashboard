# Sabarkantha Village Insights

A Flask dashboard for the supplied simulated Sabarkantha village dataset. The current workbook contains 3,500 records, 60 columns, eight talukas, and one 2024 snapshot. These synthetic records are for demonstration and should not be treated as official statistics.

## Run on Windows

From this project folder:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --default-timeout=300 --retries=10 -r requirements.txt
python app.py
```

Keep the Flask terminal open and visit <http://127.0.0.1:5000>. The workbook is read from this folder, and `instance/users.db` is created automatically. The persistent local Flask key is stored in `instance/secret_key`; it keeps sessions valid across restarts. Set `SECRET_KEY` in the environment to provide a deployment-managed key. Set `COOKIE_SECURE=1` only when serving over HTTPS.

The app can bind to the local network for a VS Code forwarded-port preview. For computer-only access, run `$env:HOST='127.0.0.1'; python app.py`. Chart.js 4.5.1 loads from cdnjs; if the CDN is unavailable, the dashboard renders accessible text summaries in place of interactive charts.

## Dashboard behavior

- Create an account with a Login ID, password, and one security question and answer. The chosen question and one-way hash of the normalized answer are stored in SQLite. Forgot-password recovery verifies that answer.
- The dataset has only one reference year, so the year selector is removed.
- Taluka and village filters apply to all summaries. Main crop applies only to agriculture and employment; demographic, education, and infrastructure metrics remain district/village measures independent of crop.
- The overview shows population, household access, literacy, digital access, sex ratio, social-group shares, village size, utilities, and facility coverage. Additional pages cover education, infrastructure, agriculture, and employment.
- The explorer supports village/taluka search, sortable columns, pagination, column selection, and CSV export of either visible or all dataset columns. A generated data dictionary CSV is available because this workbook does not include a `Data_Dictionary` sheet.
- The methodology page defines each KPI and identifies limitations. Geographic coordinates are illustrative; no map is presented as an official boundary or location source.
- Navigation, filters, and explorer state are encoded in the URL. Filter requests cascade, show loading feedback, and cancel stale requests.

## Aggregation notes

All totals and rates are calculated from the selected workbook rows. District-wide population and household counts are sums; rates and numeric indicators are means of village records unless explicitly described as population-weighted. Binary facility availability is the share of villages with a facility. Gender literacy is displayed as male and female averages with the percentage-point gap. Crop filtering does not change the demographic or service denominator.

## Backend checks

```powershell
python -m unittest discover -s tests -v
```

## Account database

User accounts are stored in `instance/users.db` beside `app.py`. Open it with a SQLite viewer such as DB Browser for SQLite. The `users` table stores the login ID, password hash, security question key, and security-answer hash; it does not store the answer as readable text. On startup, older two-question databases are migrated by keeping the first question and removing the obsolete second-question and recovery-code columns. Older accounts without a security question are prompted to add one after they sign in.

## Project files

- `app.py` — workbook loading, authentication, APIs, aggregation, exports.
- `templates/index.html` — responsive dashboard and account screens.
- `static/app.js` — URL state, accessible charts, filters, explorer and auth flows.
- `static/styles.css`, `static/accessibility.css` — dashboard styling and accessibility adjustments.
- `sabarkantha_synthetic_visualization_2024_3500_records (2).xlsx` — current supplied workbook.
- `instance/users.db`, `instance/secret_key` — local runtime account data and persistent session key; do not publish these files.
