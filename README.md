# Task API

A simple CRUD API for managing a to-do list using Python and FastAPI.

## Features

- Create tasks
- Read all tasks
- Read a task by ID
- Update tasks
- Delete tasks
- Input validation
- Swagger UI documentation
- In-memory data storage

## Requirements

- Python 3.10+
- FastAPI
- Uvicorn

## Installation & Run

Install dependencies:

```bash
pip install -r requirements.txt

Run the API:

uvicorn app.main:app --reload

The API will run at:

http://127.0.0.1:8000

Swagger UI:

http://127.0.0.1:8000/docs
Endpoints
Method	Endpoint	Description
GET	/	Get API information
GET	/health	Check API health
GET	/tasks	Get all tasks
GET	/tasks/{task_id}	Get a task by ID
POST	/tasks	Create a new task
PUT	/tasks/{task_id}	Update a task
DELETE	/tasks/{task_id}	Delete a task
Status Codes
Status Code	Description
200	Successful request
201	Task successfully created
204	Task successfully deleted
400	Invalid request body
404	Task not found
Example

Create a new task:

curl -i -X POST "http://127.0.0.1:8000/tasks" ^
  -H "Content-Type: application/json" ^
  -d "{\"title\":\"Buy milk\"}"
Swagger UI

Swagger UI is available at:

http://127.0.0.1:8000/docs

Notes

This API uses in-memory storage. Tasks will be lost when the server is restarted.

No database is used in this assignment.