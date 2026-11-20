# Smart Campus

Smart Campus is a campus space and resource booking application. It pairs a vanilla JavaScript single-page frontend with a FastAPI backend and a MySQL database. Users can browse resources, request and manage bookings, and use related tools for timetables, approvals, equipment, maintenance, societies, notifications, and reports. Access is controlled by user role.

## Project layout

```text
Smart_campus/
├── backend/
│   ├── app/                  # FastAPI routes, schemas, database and services
│   ├── scripts/              # Database checks and admin seeding
│   ├── tests/                # Backend tests
│   ├── requirements.txt
│   └── .env.example          # Backend configuration template
├── database/
│   ├── schema.sql            # MySQL schema
│   ├── migrations/           # SQL migrations and migration runners
│   └── seeds/                # Optional seed data
├── frontend/                 # Frontend served by the included launch scripts
│   ├── index.html
│   ├── css/
│   └── js/
├── index.html, css/, js/     # Root-level static-host copy of the frontend
├── run_all.bat               # Start backend and frontend on Windows
├── run_backend.bat
└── run_frontend.bat
```

The Windows launch scripts serve `frontend/`. The root-level `index.html`, `css/`, and `js/` are a second copy intended for static hosts configured to publish the repository root. Keep the copies synchronized when changing frontend files.

## Requirements

- Python 3.10 or newer
- MySQL 8.0
- A modern browser

## Setup

### 1. Configure MySQL

Create a MySQL database named `smart_campus`, then initialize it with [`database/schema.sql`](database/schema.sql). Configure the database connection in `backend/.env` using [`backend/.env.example`](backend/.env.example) as a template. Set a strong, unique `SECRET_KEY`; fill in the database host, port, user, and password for your environment. Do not commit `.env` files or production secrets.

For an existing installation, apply the migration scripts in order when they have not already been applied. Migration runners are in `database/migrations/`; the available Python runners cover migrations 001 through 014. Migration 015 is a SQL performance-index migration and has no Python runner.

### 2. Install backend dependencies

From the repository root, run:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

If PowerShell blocks activation, run the commands below with the virtual environment's Python directly, for example `..\backend\.venv\Scripts\python.exe -m pip install -r requirements.txt` from the repository root.

### 3. Create an administrator

After configuring the database, run the admin seeding script. It prompts for the account details:

```powershell
cd backend
python scripts/seed_admin.py
```

## Run locally

With Python dependencies and the database configured, run `run_all.bat` from the repository root. It starts both servers and opens the frontend.

You can also start them separately:

```powershell
# Terminal 1: backend
cd backend
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

```powershell
# Terminal 2: frontend
cd frontend
python -m http.server 5500
```

Open <http://localhost:5500>. The backend API is at <http://127.0.0.1:8000>; interactive API documentation is at <http://127.0.0.1:8000/docs>, and the health endpoint is <http://127.0.0.1:8000/health>.

## Tests and database check

From the repository root, install the backend requirements and run the tests with:

```powershell
cd backend
python -m pytest
```

To check MySQL connectivity, run `python scripts/test_db.py` from `backend/`.

## Configuration notes

- Backend settings are loaded from `backend/.env`; use `backend/.env.example` as the template.
- `CORS_ORIGINS` must include the origin serving the frontend, such as `http://localhost:5500`.
- `CAMPUS_TIMEZONE` controls the timezone used to classify schedule dates. The default is `Asia/Kolkata`.
- Authentication uses expiring JWT access tokens; passwords are hashed with Argon2id.
- Booking availability accounts for configured operating hours, timetable entries, reservations, maintenance, and blackout periods.
