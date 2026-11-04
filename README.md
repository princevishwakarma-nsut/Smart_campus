# Smart Campus — Space & Resource Booking System

A full-stack, enterprise campus resource booking platform with conflict-free academic timetable scheduling, multi-resource reservations, automated approvals, equipment tracking, society management, and role-based access control.

---

## 1. System Architecture

```text
Smart-Campus/
│
├── frontend/                     # Pure Vanilla JS Frontend (Strict Design Preserved)
│   ├── index.html                # SPA Shell
│   ├── css/
│   │   └── style.css             # Unified CSS Design System (Custom variables, responsive layout)
│   └── js/
│       ├── config.js             # API base URL & token storage keys
│       ├── api.js                # Centralized Fetch client with JWT authorization
│       ├── auth.js               # Authentication, Argon2id verification, session state
│       ├── navigation.js         # View routing & role guards
│       ├── resources.js          # Catalog & resource management (MySQL-backed)
│       ├── bookings.js           # Conflict-free booking engine & reschedule modal
│       ├── approvals.js          # Admin approval & rejection queue
│       ├── maintenance.js        # Maintenance tracking & blackout periods
│       ├── notifications.js      # User alerts & read/unread counters
│       ├── societies.js          # Student societies & membership roles
│       ├── equipment.js          # Media & equipment inventory management
│       ├── reports.js            # KPI dashboards & peak-hour analytics
│       └── app.js                # Application entrypoint & DOM event bindings
│
├── backend/                      # Python FastAPI REST API Backend
│   ├── app/
│   │   ├── main.py               # Application entrypoint, CORS, lifespan, Swagger docs
│   │   ├── core/
│   │   │   ├── config.py         # Pydantic Settings & environment loader
│   │   │   ├── security.py       # Argon2id password hashing & PyJWT token handling
│   │   │   └── permissions.py    # Role-based access control (Student, Faculty, Admin, Staff)
│   │   ├── database/
│   │   │   ├── connection.py     # Centralized MySQL connection pool
│   │   │   ├── dependencies.py   # FastAPI request-scoped DB session dependency
│   │   │   └── transaction.py    # Atomic database transaction manager
│   │   ├── api/v1/
│   │   │   ├── router.py         # Versioned API Router
│   │   │   └── endpoints/        # 47 REST endpoints
│   │   │       ├── auth.py
│   │   │       ├── users.py
│   │   │       ├── departments.py
│   │   │       ├── categories.py
│   │   │       ├── resources.py
│   │   │       ├── timetable.py
│   │   │       ├── bookings.py
│   │   │       ├── approvals.py
│   │   │       ├── equipment.py
│   │   │       ├── societies.py
│   │   │       ├── maintenance.py
│   │   │       ├── checkins.py
│   │   │       ├── notifications.py
│   │   │       └── reports.py
│   │   ├── schemas/              # Pydantic request/response models
│   │   └── services/             # Timetable availability engine & booking workflows
│   ├── scripts/
│   │   ├── test_db.py            # MySQL connectivity verification
│   │   └── seed_admin.py         # Secure Argon2id Admin creation
│   ├── tests/
│   │   └── test_api.py           # Comprehensive integration & unit test suite
│   ├── requirements.txt          # Python dependencies
│   ├── .env                      # Environment configuration (ignored in git)
│   └── .env.example              # Template environment file
│
├── database/
│   ├── schema.sql                # Complete MySQL schema dump
│   ├── seeds/                    # Seed configurations
│   └── migrations/               # Database migrations
│
└── .gitignore
```

---

## 2. Requirements & Prerequisites

* **Python**: 3.10, 3.11, 3.12, or 3.13
* **Database**: MySQL 8.0 Server (Database name: `smart_campus`)
* **Browser**: Modern web browser (Chrome, Edge, Firefox, Safari)

---

## 3. Installation & Setup

### A. Clone and Install Python Dependencies
```bash
cd backend
python -m pip install -r requirements.txt
```

### B. Environment Configuration
Copy `.env.example` to `.env` in `backend/.env`:
```ini
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=root
DB_PASSWORD=your_mysql_password
DB_NAME=smart_campus
CAMPUS_TIMEZONE=Asia/Kolkata
SECRET_KEY=smart_campus_secure_jwt_secret_key_2026_nsut_production_ready
ACCESS_TOKEN_EXPIRE_MINUTES=1440
CORS_ORIGINS=["http://localhost:5500", "http://127.0.0.1:5500", "http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:8000", "http://127.0.0.1:8000", "http://localhost:8080", "http://127.0.0.1:8080", "null"]
```

### C. Verify Database Connection
```bash
python test_db.py
```

For an existing database, apply the notification audience migration from the project root:
```bash
python database/migrations/apply_007_notifications.py
python database/migrations/apply_008_settings.py
python database/migrations/apply_009_resource_hours.py
python database/migrations/apply_010_blackout_management.py
python database/migrations/apply_011_blackout_exclusions.py
python database/migrations/apply_012_operating_hours_and_maintenance.py
python database/migrations/apply_013_operating_hours_activation.py
python database/migrations/apply_014_equipment_blackouts.py
```
Migration 008 adds persisted Admin-managed booking rules (academic year and timetable enforcement, advance window, duration limits, approval workflow, and cancellation cutoff). Migration 009 adds the optional legacy resource operating-hours field. Migration 010 adds linked bulk blackout metadata, reason categories and explanations, and historical cancellation state. Migration 011 stores category-selection exclusions so bulk blackout edits preserve individually removed resources. Migration 012 adds audited recurring weekly resource schedules, date-specific operating-hours exceptions, and a maintenance type field. Migration 013 adds an active switch for recurring schedules while preserving existing schedule rows. Migration 014 adds additive, audited equipment blackout periods. Configure bulk resource hours and exceptions from **Admin → Resource Inventory → Operating Hours**; the schedule form defaults to 08:00–18:00 every day, with the remaining hours unavailable after the schedule is applied. Booking validation enforces active configured hours, exceptions, blackouts, and pending or approved reservations. Blackout windows can target spaces or equipment, and selected weekdays (such as Monday–Friday) create separate dated occurrences through the selected end date. Blackout creation with overlapping bookings requires explicit Admin confirmation; it preserves existing bookings and notifies affected users. Maintenance overlapping existing bookings also requires explicit conflict review and confirmation. These migrations are additive and preserve existing booking and inventory data. After applying migration 008, configure booking rules from **Admin → Settings**. Authentication tokens and cached users are stored per browser tab, so separate tabs can use separate accounts.
`CAMPUS_TIMEZONE` sets the IANA timezone used by the backend to classify today's and upcoming schedule bookings; it defaults to `Asia/Kolkata`.

### D. Seed the Initial Admin Account (if not already seeded)
```bash
python seed_admin.py
```

---

## 4. Running the Application

### A. Run Backend API
```bash
cd backend
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```
* **Interactive Swagger UI**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
* **ReDoc Documentation**: [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)
* **Health Check**: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)

### B. Run Frontend
Open `frontend/index.html` (or root `index.html`) using VS Code Live Server (or any static HTTP server on port 5500 or 8080):
```bash
# Example with python http.server:
cd frontend
python -m http.server 5500
```
Open `http://localhost:5500` in your web browser.

---

## 5. Running Tests

Execute the comprehensive test suite:
```bash
cd backend
python tests/test_api.py
```

---

## 6. Security Features

* **Password Hashing**: Argon2id via `argon2-cffi`.
* **Tokens**: Cryptographic HS256 JWT tokens with automatic expiry.
* **SQL Injection Protection**: 100% parameterized queries using `mysql-connector-python`.
* **Atomic Transactions**: Multi-table consistency via context-managed database transactions.
* **Role-Based Access Control**: Backend-enforced permissions for Student, Faculty, Staff, and Admin.
