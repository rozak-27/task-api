import sqlite3

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

app = FastAPI(
    title="Task API",
    version="1.0",
    description="A simple CRUD API for managing tasks."
)

DATABASE = "tasks.db"


def get_connection():
    return sqlite3.connect(DATABASE)


def init_db():
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            done BOOLEAN NOT NULL DEFAULT 0
        )
    """)

    cursor.execute("SELECT COUNT(*) FROM tasks")
    count = cursor.fetchone()[0]

    if count == 0:
        cursor.executemany(
            "INSERT INTO tasks (id, title, done) VALUES (?, ?, ?)",
            [
                (1, "Learn FastAPI", 0),
                (2, "Build CRUD API", 0),
                (3, "Test API with Swagger", 1)
            ]
        )

    connection.commit()
    connection.close()


init_db()


class TaskCreate(BaseModel):
    title: str


class TaskUpdate(BaseModel):
    title: str | None = None
    done: bool | None = None


@app.get(
    "/",
    description="Get API information and available endpoints."
)
def root():
    return {
        "name": "Task API",
        "version": "1.0",
        "endpoints": ["/tasks"]
    }


@app.get(
    "/health",
    description="Check whether the API is running."
)
def health():
    return {"status": "ok"}


@app.get(
    "/tasks",
    description="Get all tasks."
)
def get_tasks():
    connection = get_connection()
    connection.row_factory = sqlite3.Row
    cursor = connection.cursor()

    cursor.execute("SELECT * FROM tasks")
    rows = cursor.fetchall()

    connection.close()

    return [dict(row) for row in rows]


@app.get(
    "/tasks/{task_id}",
    description="Get a task by its ID."
)
def get_task(task_id: int):
    connection = get_connection()
    connection.row_factory = sqlite3.Row
    cursor = connection.cursor()

    cursor.execute(
        "SELECT * FROM tasks WHERE id = ?",
        (task_id,)
    )

    row = cursor.fetchone()

    connection.close()

    if row is None:
        return JSONResponse(
            status_code=404,
            content={"error": "Task not found"}
        )

    return dict(row)


@app.post(
    "/tasks",
    status_code=201,
    description="Create a new task."
)
def create_task(task: TaskCreate):
    title = task.title.strip()

    if not title:
        raise HTTPException(
            status_code=400,
            detail="Title cannot be empty"
        )

    connection = get_connection()
    connection.row_factory = sqlite3.Row
    cursor = connection.cursor()

    cursor.execute(
        "INSERT INTO tasks (title, done) VALUES (?, ?)",
        (title, 0)
    )

    new_id = cursor.lastrowid

    connection.commit()

    cursor.execute(
        "SELECT * FROM tasks WHERE id = ?",
        (new_id,)
    )

    row = cursor.fetchone()

    connection.close()

    return dict(row)


@app.put(
    "/tasks/{task_id}",
    description="Update an existing task."
)
def update_task(task_id: int, task_update: TaskUpdate):
    connection = get_connection()
    connection.row_factory = sqlite3.Row
    cursor = connection.cursor()

    # Check whether the task exists
    cursor.execute(
        "SELECT * FROM tasks WHERE id = ?",
        (task_id,)
    )

    existing_task = cursor.fetchone()

    if existing_task is None:
        connection.close()

        return JSONResponse(
            status_code=404,
            content={"error": "Task not found"}
        )

    # Keep the existing values if they are not provided
    current_title = existing_task["title"]
    current_done = existing_task["done"]

    new_title = current_title
    new_done = current_done

    if task_update.title is not None:
        new_title = task_update.title.strip()

        if not new_title:
            connection.close()

            raise HTTPException(
                status_code=400,
                detail="Title cannot be empty"
            )

    if task_update.done is not None:
        new_done = int(task_update.done)

    cursor.execute(
        """
        UPDATE tasks
        SET title = ?, done = ?
        WHERE id = ?
        """,
        (new_title, new_done, task_id)
    )

    connection.commit()

    cursor.execute(
        "SELECT * FROM tasks WHERE id = ?",
        (task_id,)
    )

    updated_task = cursor.fetchone()

    connection.close()

    return dict(updated_task)


@app.delete(
    "/tasks/{task_id}",
    status_code=204,
    description="Delete a task."
)
def delete_task(task_id: int):
    connection = get_connection()
    cursor = connection.cursor()

    # Check whether the task exists
    cursor.execute(
        "SELECT id FROM tasks WHERE id = ?",
        (task_id,)
    )

    task = cursor.fetchone()

    if task is None:
        connection.close()

        return JSONResponse(
            status_code=404,
            content={"error": "Task not found"}
        )

    cursor.execute(
        "DELETE FROM tasks WHERE id = ?",
        (task_id,)
    )

    connection.commit()
    connection.close()

    return None