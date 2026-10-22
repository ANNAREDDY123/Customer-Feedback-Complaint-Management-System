
# Customer Feedback & Complaint Management System

A Python FastAPI backend for managing customer feedback, complaints, support assignments, resolution workflows, service-level agreements (SLAs), notifications, reports, and audit logs.

## Features

- **Authentication and Authorization** — Password hashing, JWT authentication, and role-based access control.
- **Customer Management** — Manage customer records.
- **Feedback Management** — Submit and manage customer feedback.
- **Category Management** — Organize complaints using categories.
- **Complaint Management** — Create, track, search, filter, and manage complaints.
- **Agent Assignment** — Assign and reassign complaints to support agents.
- **Resolution Workflow** — Track complaint status changes, comments, internal notes, and history.
- **SLA Management** — Support service-level agreement tracking.
- **Notifications** — Notify users about relevant complaint activities.
- **Reports and Analytics** — Generate complaint reports and analytics.
- **Report Export** — Export supported reports to CSV.
- **Bulk Operations** — Perform supported bulk complaint operations.
- **Audit Logs** — Record important actions, including complaint creation, status changes, and agent assignments.
- **Automated Tests** — Validate application functionality using pytest.
- **Interactive API Documentation** — Explore endpoints using Swagger UI.

## Technology Stack

- Python
- FastAPI
- SQLAlchemy
- Pydantic
- SQLite (default configuration)
- JWT authentication
- Passlib and bcrypt for password hashing
- Pytest
- Uvicorn

## Project Structure

```text
customer-feedback-complaint-management/
├── app/
│   ├── api/
│   │   ├── agents.py
│   │   ├── audit_logs.py
│   │   ├── auth.py
│   │   ├── bulk_operations.py
│   │   ├── categories.py
│   │   ├── complaints.py
│   │   ├── customers.py
│   │   ├── deps.py
│   │   ├── feedback.py
│   │   ├── notifications.py
│   │   ├── reports.py
│   │   ├── resolution.py
│   │   ├── sla.py
│   │   └── users.py
│   ├── core/
│   │   ├── bootstrap.py
│   │   ├── config.py
│   │   └── security.py
│   ├── db/
│   │   └── database.py
│   ├── models/
│   ├── schemas/
│   ├── services/
│   └── main.py
├── scripts/
├── tests/
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

## Prerequisites

Install the following before running the application:

- Python 3.11 or a compatible version supported by the dependencies.
- Git (optional, for cloning the repository).
- PowerShell on Windows, or an equivalent terminal.

## Installation and Setup

### 1. Clone the repository

```bash
git clone https://github.com/ANNAREDDY123/Customer-Feedback-Complaint-Management-System.git
cd Customer-Feedback-Complaint-Management-System
```

Alternatively, if you already have the project locally, navigate to its root directory.

### 2. Create a virtual environment

On Windows PowerShell:

```powershell
python -m venv venv
```

Activate it:

```powershell
.\venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, you can use the virtual environment's Python directly:

```powershell
.\venv\Scripts\python.exe -m pip --version
```

### 3. Install dependencies

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Configure environment variables

Create your local environment file:

```powershell
Copy-Item .env.example .env
```

Open `.env` and configure the values for your environment:

```dotenv
APP_NAME=Customer Feedback & Complaint Management System
DATABASE_URL=sqlite:///./customer_feedback.db
SECRET_KEY=replace-with-a-unique-random-secret
ACCESS_TOKEN_EXPIRE_MINUTES=30
ADMIN_EMAIL=admin@example.com
ADMIN_PASSWORD=replace-with-a-strong-admin-password
```

**Security requirements:**

- Replace the example secret with a strong, randomly generated secret.
- Set a strong administrator password.
- Never commit `.env` or real credentials to GitHub.
- Keep `.env.example` limited to placeholders and non-sensitive defaults.

You can generate a random secret using Python:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Copy the generated value into the `SECRET_KEY` setting in `.env`.

### 5. Initialize application data

Follow the application's existing initialization and bootstrap logic in `app/db/database.py` and `app/core/bootstrap.py`.

If an administrator account must be created, use the project's supported bootstrap process. Do not assume that setting `ADMIN_EMAIL` and `ADMIN_PASSWORD` automatically creates the account unless the bootstrap code does so.

## Running the Application

From the project root, with the virtual environment activated:

```powershell
uvicorn app.main:app --reload
```

The development server normally starts at:

http://127.0.0.1:8000

If the server reports an initialization or configuration error, check the terminal output and your `.env` settings.

## API Documentation

Once the application is running, open:

- **Swagger UI:** http://127.0.0.1:8000/docs
- **ReDoc:** http://127.0.0.1:8000/redoc

Use the interactive documentation to inspect available endpoints, review request and response schemas, and test API operations.

For protected endpoints, authenticate using the API's login endpoint and supply the returned bearer token as required.

## Running Tests

Run the complete test suite from the project root:

```powershell
$env:PYTHONPATH = (Get-Location).Path
python -m pytest -q
```

Run individual test modules when needed:

```powershell
python -m pytest -q tests/test_auth.py
python -m pytest -q tests/test_complaints.py
python -m pytest -q tests/test_agent_assignment.py
python -m pytest -q tests/test_audit_logs.py
```

The latest test run during development reported **146 passed, 1 warning**. Results may differ as the code or environment changes.

The existing warning concerns the use of `httpx` with Starlette's test client. It did not cause a test failure in that run.

## Security Considerations

- Store secrets and credentials in environment variables.
- Do not commit `.env`, local databases, virtual environments, or Python cache files.
- Use HTTPS when deploying outside a local development environment.
- Configure a unique secret key before deployment.
- Use strong administrator credentials.
- Grant roles only the permissions required for each user.
- Review audit logs when investigating important application actions.
- Keep dependencies updated and review security advisories.

## Current Scope

This repository provides a backend application. Deployment infrastructure, production database configuration, external notification providers, and other integrations should be verified against the actual environment before being described as production-ready.

## Author

**Jagadeswar Reddy**

GitHub: https://github.com/ANNAREDDY123

## License

No license has been specified. All rights are reserved unless a license is added to this repository.
'@ | Set-Content -Encoding utf8 README.md
