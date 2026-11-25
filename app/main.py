import os

import psycopg
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.supabase_client import supabase

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

app = FastAPI(
    title="Task API",
    version="1.0.0",
    description="A secure Task & Authentication API powered by FastAPI and Supabase Auth.",
)


@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request: Request, exc: StarletteHTTPException):
    if isinstance(exc.detail, dict) and "error" in exc.detail:
        content = exc.detail
    else:
        content = {"error": str(exc.detail)}
    return JSONResponse(
        status_code=exc.status_code,
        content=content,
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=400,
        content={"error": "Invalid request body or missing required fields"},
    )


# ==========================================
# DATABASE CONFIGURATION (OPTIONAL FOR AUTH)
# ==========================================

def get_connection():
    if not DATABASE_URL:
        raise HTTPException(status_code=503, detail="DATABASE_URL is not configured")
    try:
        return psycopg.connect(DATABASE_URL, connect_timeout=3)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="PostgreSQL database is unavailable") from exc


def init_db():
    if not DATABASE_URL:
        return
    try:
        connection = psycopg.connect(DATABASE_URL, connect_timeout=2)
        cursor = connection.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                done BOOLEAN NOT NULL DEFAULT FALSE
            )
            """
        )
        cursor.execute("SELECT COUNT(*) FROM tasks")
        count = cursor.fetchone()[0]
        if count == 0:
            cursor.executemany(
                "INSERT INTO tasks (title, done) VALUES (%s, %s)",
                [
                    ("Learn FastAPI", False),
                    ("Build CRUD API", False),
                    ("Test API with Swagger", True),
                ],
            )
        connection.commit()
        connection.close()
    except Exception:
        # Allow standalone auth server startup when local Postgres container is stopped
        pass


init_db()


# ==========================================
# PYDANTIC MODELS
# ==========================================

class TaskCreate(BaseModel):
    title: str


class TaskUpdate(BaseModel):
    title: str | None = None
    done: bool | None = None


class AuthRequest(BaseModel):
    email: str | None = None
    password: str | None = None

# ==========================================
# AUTHENTICATION ENDPOINTS
# ==========================================

@app.post(
    "/auth/signup",
    status_code=201,
    tags=["Auth"],
    summary="Register a new user account",
)
def signup(auth: AuthRequest | None = None):
    if auth is None:
        raise HTTPException(status_code=400, detail="Email and password are required")

    email = (auth.email or "").strip()
    password = auth.password or ""

    if not email or not password:
        raise HTTPException(status_code=400, detail="Email and password are required")

    try:
        response = supabase.auth.sign_up({"email": email, "password": password})
        if response.user is None:
            raise HTTPException(status_code=400, detail="Unable to create user account")
        return response.user.model_dump(mode="json")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post(
    "/auth/login",
    status_code=200,
    tags=["Auth"],
    summary="Authenticate user and return JWT tokens",
)
def login(auth: AuthRequest | None = None):
    if auth is None:
        raise HTTPException(status_code=400, detail="Email and password are required")

    email = (auth.email or "").strip()
    password = auth.password or ""

    if not email or not password:
        raise HTTPException(status_code=400, detail="Email and password are required")

    try:
        response = supabase.auth.sign_in_with_password(
            {"email": email, "password": password}
        )
        if response.session is None:
            raise HTTPException(status_code=401, detail="Invalid login credentials")

        return {
            "access_token": response.session.access_token,
            "refresh_token": response.session.refresh_token,
            "token_type": "bearer",
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid login credentials") from exc

# ==========================================
# PUBLIC & PROTECTED ENDPOINTS
# ==========================================

def extract_bearer_token(request: Request) -> str:
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        raise HTTPException(status_code=401, detail="Access token required")

    parts = auth_header.split(" ")
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise HTTPException(status_code=401, detail="Access token required")

    return parts[1].strip()


@app.get("/public/info", tags=["Public"], summary="Read public open data")
def public_info():
    return {"message": "Welcome stranger! This info is public."}


@app.get("/protected/profile", tags=["Protected"], summary="Read private profile data")
def protected_profile(request: Request):
    token = extract_bearer_token(request)
    return {"message": "Token received", "token_preview": f"{token[:12]}..."}

# ==========================================
# GENERAL & TASK CRUD ENDPOINTS
# ==========================================

@app.get("/", tags=["General"], summary="Get API overview")
def root():
    return {
        "name": "Task API",
        "version": "1.0.0",
        "docs": "/docs",
    }


@app.get("/health", tags=["General"], summary="Health check")
def health():
    return {"status": "ok"}


@app.get("/tasks", tags=["Tasks"], summary="Get all tasks")
def get_tasks():
    connection = get_connection()
    cursor = connection.cursor()
    cursor.execute("SELECT id, title, done FROM tasks ORDER BY id")
    rows = cursor.fetchall()
    connection.close()
    return [{"id": row[0], "title": row[1], "done": row[2]} for row in rows]


@app.get("/tasks/{task_id}", tags=["Tasks"], summary="Get a task by ID")
def get_task(task_id: int):
    connection = get_connection()
    cursor = connection.cursor()
    cursor.execute("SELECT id, title, done FROM tasks WHERE id = %s", (task_id,))
    row = cursor.fetchone()
    connection.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"id": row[0], "title": row[1], "done": row[2]}


@app.post("/tasks", status_code=201, tags=["Tasks"], summary="Create a new task")
def create_task(task: TaskCreate):
    title = task.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title cannot be empty")
    connection = get_connection()
    cursor = connection.cursor()
    cursor.execute(
        "INSERT INTO tasks (title, done) VALUES (%s, %s) RETURNING id, title, done",
        (title, False),
    )
    row = cursor.fetchone()
    connection.commit()
    connection.close()
    return {"id": row[0], "title": row[1], "done": row[2]}


@app.put("/tasks/{task_id}", tags=["Tasks"], summary="Update an existing task")
def update_task(task_id: int, task_update: TaskUpdate):
    connection = get_connection()
    cursor = connection.cursor()
    cursor.execute("SELECT id, title, done FROM tasks WHERE id = %s", (task_id,))
    existing_task = cursor.fetchone()
    if existing_task is None:
        connection.close()
        raise HTTPException(status_code=404, detail="Task not found")

    new_title = existing_task[1]
    new_done = existing_task[2]

    if task_update.title is not None:
        new_title = task_update.title.strip()
        if not new_title:
            connection.close()
            raise HTTPException(status_code=400, detail="Title cannot be empty")

    if task_update.done is not None:
        new_done = task_update.done

    cursor.execute(
        "UPDATE tasks SET title = %s, done = %s WHERE id = %s RETURNING id, title, done",
        (new_title, new_done, task_id),
    )
    updated_task = cursor.fetchone()
    connection.commit()
    connection.close()
    return {"id": updated_task[0], "title": updated_task[1], "done": updated_task[2]}


@app.delete("/tasks/{task_id}", status_code=204, tags=["Tasks"], summary="Delete a task")
def delete_task(task_id: int):
    connection = get_connection()
    cursor = connection.cursor()
    cursor.execute("SELECT id FROM tasks WHERE id = %s", (task_id,))
    task = cursor.fetchone()
    if task is None:
        connection.close()
        raise HTTPException(status_code=404, detail="Task not found")
    cursor.execute("DELETE FROM tasks WHERE id = %s", (task_id,))
    connection.commit()
    connection.close()
    return Response(status_code=204)
