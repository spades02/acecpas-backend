# AceCPAs Backend

Multi-tenant Financial Intelligence Platform backend with AI-powered GL transaction mapping.

## Tech Stack

- **API**: FastAPI (Python 3.11+)
- **Database**: Supabase PostgreSQL 15 + pgvector
- **Auth**: Supabase Auth
- **Async Tasks**: Celery + Redis
- **AI**: LangGraph + OpenAI GPT-4o

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env with your credentials
```

### 3. Run Database Migrations

Run `sql/schema.sql` in your Supabase SQL Editor.

### 4. Start the API

```bash
uvicorn app.main:app --reload
```

### 5. Start Celery Worker

```bash
celery -A app.workers.celery_app worker --loglevel=info
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/upload` | POST | Upload Excel GL file |
| `/deals/{id}/grid` | GET | Paginated transactions |
| `/deals/{id}/approve-map` | POST | Verify mappings |
| `/deals/{id}/open-items` | GET | List audit questions |
| `/deals/{id}/generate-report` | POST | Generate Excel report |

## Project Structure

```
app/
├── main.py              # FastAPI entry point
├── config.py            # Environment configuration
├── database.py          # Supabase client
├── models/schemas.py    # Pydantic models
├── routers/             # API endpoints
├── services/            # Business logic
└── workers/             # Celery tasks
```
