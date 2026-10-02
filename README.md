# Task API

A simple CRUD API built with FastAPI and PostgreSQL.

For this assignment, the API runs together with PostgreSQL using Docker Compose.

## What This Project Does

This project provides a simple Task API with CRUD operations:

- Create a task
- Read all tasks
- Read a task by ID
- Update a task
- Delete a task

The database is PostgreSQL and runs inside a Docker container.

## Run with Docker Compose

Make sure Docker Desktop is running.

Create `.env` from `.env.example` if needed:

```powershell
Copy-Item .env.example .env

Start the API and PostgreSQL with one command:

docker compose up

The API will be available at:

http://localhost:3000

Swagger UI:

http://localhost:3000/docs

To stop the stack:

docker compose down

The PostgreSQL data is stored in a Docker volume named taskdata, so the data persists after the containers are stopped.

Environment Variables

The database connection is configured using DATABASE_URL.

Example:

DATABASE_URL=postgres://postgres:dev@localhost:5433/tasks

The .env file is ignored by Git.

.env.example is included in the repository as a template.

Database

PostgreSQL runs in a Docker container using the official PostgreSQL 17 image.

The database and tasks table are created automatically when the application starts.

When the table is empty, the application creates three seed tasks:

Learn FastAPI
Build CRUD API
Test API with Swagger

The API connects to PostgreSQL using the Docker Compose service name:

db:5432
API Endpoints
Method	Endpoint	Description
GET	/	Get API information
GET	/health	Check API health
GET	/tasks	Get all tasks
GET	/tasks/{task_id}	Get a task by ID
POST	/tasks	Create a task
PUT	/tasks/{task_id}	Update a task
DELETE	/tasks/{task_id}	Delete a task
Example Request

Create a task:

$body = @{
    title = "Test Docker Persistence"
} | ConvertTo-Json

Invoke-RestMethod `
    -Uri "http://localhost:3000/tasks" `
    -Method Post `
    -ContentType "application/json" `
    -Body $body

Example response:

{
  "id": 4,
  "title": "Test Docker Persistence",
  "done": false
}
Database Persistence

The PostgreSQL database uses a Docker volume:

taskdata

This allows task data to remain available after:

docker compose down

and starting the stack again with:

docker compose up

For example, task 4 was created before restarting the stack and was still available afterward.

Database Check

PostgreSQL can be accessed from the database container:

docker compose exec db psql -U postgres -d tasks

Inside psql, check the tables:

\dt

Check the task data:

SELECT * FROM tasks;

Exit with:

\q
Docker Stack

The project contains two services:

Docker Compose
├── api
│   └── FastAPI
│
└── db
    └── PostgreSQL 17

The API connects to PostgreSQL through the Compose service name db.

Project Structure
task-api/
├── app/
│   ├── __init__.py
│   └── main.py
├── Dockerfile
├── compose.yaml
├── .env.example
├── .gitignore
├── README.md
└── requirements.txt