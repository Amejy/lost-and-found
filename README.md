# Web-Based Lost and Found Management System

A production-oriented lost and found platform built with Flask, SQLAlchemy, Bootstrap, and a PostgreSQL-ready relational schema. The application supports user registration, role-based access control, lost/found item reporting, automatic matching, ownership claims, admin review workflows, and in-app notifications.

## Features

- User registration, login, logout, password hashing, and role-based access (`user`, `admin`)
- Lost item and found item reporting with optional image uploads
- Search and filter by keyword, category, location, and date
- Automatic match suggestions using description, category, location, and date proximity
- Ownership claim submission with optional supporting image
- Admin dashboard for reviewing claims, managing users, and deleting records
- Web-based editing flow for existing lost/found records
- RESTful JSON API for authentication, items, claims, and admin reporting
- In-app notifications for match alerts and claim decisions
- PostgreSQL schema plus SQLite development fallback for quick local startup

## Stack

- Frontend: HTML, Bootstrap 5, custom CSS, vanilla JavaScript
- Backend: Python 3.12, Flask, Flask-Login, Flask-WTF, SQLAlchemy
- Database: PostgreSQL preferred, SQLite fallback for local development

## Project Structure

```text
backend/
  app/
    forms/
    models/
    routes/
    services/
    static/
    templates/
database/
  schema.sql
uploads/
run.py
requirements.txt
README.md
```

## Setup

1. Create and activate a virtual environment.
2. Install dependencies.
3. Configure environment variables.
4. Run the Flask app.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
export $(grep -v '^#' .env | xargs)
flask --app run.py init-db
export PORT=5001
python run.py
```

The app will start on `http://127.0.0.1:5001`.

Notes:

- `run.py` uses a quiet local server path for browser testing, without the Flask startup warning banner.
- For real deployment, use a dedicated production WSGI server such as Waitress, Gunicorn, or uWSGI.
- To test an admin account and a normal user at the same time, use separate browser profiles or an incognito window, since one browser session can only stay logged in as one account at a time.

## Deployment

This project is best deployed as a single Flask web service with:

- `Railway` for the app host
- `Railway Postgres` for the database
- A persistent volume mounted at `/data/uploads` for image uploads

### Why this setup

- The app is server-rendered Flask, so it does not need a separate Vercel frontend.
- Uploads are stored on disk by default, so the host needs persistent storage or an object-storage refactor.
- Railway can run the app, host Postgres, and provide a persistent volume without splitting the architecture.

### Docker deploy

Build the included `Dockerfile` locally or push the repo to Railway and let it build the image.

Environment variables for production:

- `SECRET_KEY`
- `DATABASE_URL`
- `UPLOAD_FOLDER=/data/uploads`
- `FLASK_ENV=production`
- `ADMIN_EMAIL`
- `ADMIN_PASSWORD`
- `ADMIN_NAME`
- `MATCH_THRESHOLD` if you want to tune matching behavior

Recommended Railway steps:

1. Create a new Railway project from this Git repository.
2. Add a Railway Postgres database.
3. Mount a persistent volume at `/data/uploads`.
4. Set the environment variables above.
5. Deploy the service from the repo root.

If you prefer a VPS, the same Docker image can run there with your own Postgres instance and a mounted upload directory.

## Database Configuration

The app defaults to SQLite for immediate local use:

```env
DATABASE_URL=sqlite:////home/mohammed/LOST-FOUND/database/lost_found.db
```

For PostgreSQL, set:

```env
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/lost_found
```

Initialize the schema with `flask --app run.py init-db`. A PostgreSQL schema is also included at [database/schema.sql](/home/mohammed/LOST-FOUND/database/schema.sql).

## Admin Bootstrap

Create an initial admin user with the included CLI command:

```bash
export FLASK_APP=run.py
flask seed-admin
```

Defaults:

- Email: `admin@lostfound.local`
- Password: `Admin12345!`

Override them with `ADMIN_EMAIL`, `ADMIN_PASSWORD`, and `ADMIN_NAME`.

## Key Routes

### Web UI

- `/register`
- `/login`
- `/dashboard`
- `/lost/report`
- `/found/report`
- `/claims`
- `/notifications`
- `/admin`

### API

- `POST /api/v1/auth/register`
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/me`
- `GET|POST /api/v1/lost-items`
- `GET|PUT|DELETE /api/v1/lost-items/<id>`
- `GET|POST /api/v1/found-items`
- `GET|PUT|DELETE /api/v1/found-items/<id>`
- `GET|POST /api/v1/claims`
- `GET /api/v1/claims/<id>`
- `PATCH /api/v1/claims/<id>/review`
- `GET /api/v1/admin/dashboard`
- `GET /api/v1/admin/users`

## Matching Logic

Potential matches are scored with a weighted heuristic:

- Description/title similarity: 45%
- Category exact match: 25%
- Location similarity: 15%
- Date proximity: 15%

When a score reaches the configured threshold (`MATCH_THRESHOLD`, default `0.55`), both reporters receive in-app notifications.

## Security Notes

- Passwords are hashed with Werkzeug’s secure password hasher
- Flask-WTF provides CSRF protection for form-based browser flows
- SQLAlchemy ORM helps prevent SQL injection risks
- User input is sanitized with `bleach`
- Role-based access checks protect admin workflows
- File uploads are extension-validated and stored with randomized names

## Optional Enhancements

- Add outbound email delivery for notifications
- Replace heuristic matching with embeddings or full-text similarity
- Add audit logging and moderation history
- Add Alembic migrations and automated tests
