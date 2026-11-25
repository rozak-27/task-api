# Task & Auth API — Supabase JWT Authentication

A secure REST API built with **FastAPI** and **Supabase Auth** (Identity Provider) implementing user registration, login, session refresh, logout, reusable JWT bearer-token verification, role-based authorization (`403 Forbidden`), login brute-force rate limiting (`429 Too Many Requests`), and interactive **Swagger UI** Bearer authentication.

---

## Architecture Overview (The Trust Triangle)

1. **Sign Up / Log In**: Client sends credentials (`email` + `password`) to this API, which delegates account creation and password verification to **Supabase Auth** (passwords are never stored or hashed locally).
2. **JWT Issuance**: Supabase signs and returns a short-lived **JWT `access_token`** and a longer-lived **`refresh_token`**.
3. **Authenticated Requests**: Client calls protected endpoints with `Authorization: Bearer <access_token>`.
4. **Verification Guard**: FastAPI's reusable `get_current_user` dependency extracts the Bearer token and verifies its cryptographic validity via `supabase.auth.get_user(token)` before allowing the route handler to execute.

---

## Quick Start (Under 5 Minutes)

### 1. Clone & Install Dependencies

```bash
git clone https://github.com/rozak-27/task-api.git
cd task-api
python -m venv .venv
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# macOS / Linux:
# source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure Environment Variables

Copy `.env.example` to `.env` (`.env` is git-ignored and never committed):

```powershell
Copy-Item .env.example .env
```

Fill in your **Supabase Project URL** and **anon public key** (from **Supabase Dashboard → Project Settings → API**):

```env
SUPABASE_URL=https://your-project-id.supabase.co
SUPABASE_KEY=your_supabase_anon_public_key
PORT=8000
DATABASE_URL=postgres://postgres:dev@localhost:5433/tasks
```

> **Supabase Dev Tip**: In **Authentication → Sign In / Providers → Email**, disable **"Confirm email"** for local testing so newly registered accounts can log in immediately. Never put your `service_role` key in `.env`.

### 3. Run the Server (Single Command)

```bash
uvicorn app.main:app --reload --port 8000
```

- **API Base URL**: `http://localhost:8000`
- **Interactive Swagger UI**: `http://localhost:8000/docs`

*(Optional: To also run the PostgreSQL container for `/tasks` CRUD endpoints, run `docker compose up --build`.)*

---

## API Reference

### Authentication & Protected Endpoints

| Method | Endpoint | Purpose | Auth Required | Status Codes |
| :--- | :--- | :--- | :--- | :--- |
| `POST` | `/auth/signup` | Create a new user account via Supabase Auth | None | `201` Created · `400` Bad Request |
| `POST` | `/auth/login` | Authenticate credentials & return `access_token` + `refresh_token` (rate-limited) | None | `200` OK · `400` Missing input · `401` Invalid credentials · `429` Rate limited |
| `POST` | `/auth/refresh` | Exchange a `refresh_token` for a fresh `access_token` | None (`refresh_token` in body) | `200` OK · `400` Missing token · `401` Invalid/expired token |
| `POST` | `/auth/logout` | End the authenticated user's session | `Authorization: Bearer <token>` | `204` No Content · `401` Unauthorized |
| `GET` | `/public/info` | Read open, public information | None | `200` OK |
| `GET` | `/protected/profile` | Read verified user profile metadata (`id`, `email`, `created_at`, `role`) | `Authorization: Bearer <token>` | `200` OK · `401` Unauthorized |
| `GET` | `/protected/dashboard` | Protected dashboard reusing the same `get_current_user` guard | `Authorization: Bearer <token>` | `200` OK · `401` Unauthorized |
| `GET` | `/protected/admin` | Admin-only endpoint (`role == "admin"`) demonstrating `403` vs `401` | `Authorization: Bearer <token>` (Admin) | `200` OK · `401` Unauthorized · `403` Forbidden |

### Task CRUD Endpoints (PostgreSQL)

| Method | Endpoint | Purpose | Auth Required |
| :--- | :--- | :--- | :--- |
| `GET` | `/tasks` | List all tasks | None |
| `GET` | `/tasks/{task_id}` | Get a single task by ID | None |
| `POST` | `/tasks` | Create a new task | None |
| `PUT` | `/tasks/{task_id}` | Update an existing task | None |
| `DELETE` | `/tasks/{task_id}` | Delete a task | None |

---

## Testing via `curl`

```bash
# 1. Sign up (201 Created)
curl -i -X POST http://localhost:8000/auth/signup \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"password123"}'

# 2. Log in (200 OK -> copy access_token)
curl -i -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"password123"}'

# 3. Call public route (200 OK)
curl -i http://localhost:8000/public/info

# 4. Call protected route with valid Bearer token (200 OK)
curl -i http://localhost:8000/protected/profile \
  -H "Authorization: Bearer <YOUR_ACCESS_TOKEN>"

# 5. Tamper with 1 character of the token (401 Unauthorized)
curl -i http://localhost:8000/protected/profile \
  -H "Authorization: Bearer <TAMPERED_ACCESS_TOKEN>"
```

---

## Swagger UI Bearer Authentication (`/docs`)

FastAPI's `HTTPBearer` security scheme adds the **Authorize** padlock button at `/docs` and marks protected endpoints (`/auth/logout`, `/protected/profile`, `/protected/dashboard`, `/protected/admin`) with lock icons:

1. Open `http://localhost:8000/docs`.
2. Execute `POST /auth/login` and copy the `access_token` string.
3. Click **Authorize** at the top right, paste your JWT `access_token`, and click **Authorize**.
4. Click **Try it out → Execute** on `GET /protected/profile` to verify your authenticated profile directly from the browser.

![Swagger UI Bearer Auth](./swagger-auth.png)

---

## Security Notes & Stretch Goals

### 1. `401 Unauthorized` vs `403 Forbidden` (`GET /protected/admin`)
- **`401 Unauthorized`** means *"I don't know who you are"* — the client sent no token, a malformed `Authorization` header, or an invalid/expired JWT (**authentication** failure).
- **`403 Forbidden`** means *"I know exactly who you are, and you still may not enter"* — the JWT verified cleanly via `get_current_user`, but `require_admin` confirmed the user lacks `role: "admin"` (**authorization** failure).

### 2. Why Access Tokens Are Short-Lived (`POST /auth/refresh`)
Access tokens are intentionally short-lived (1 hour by default in Supabase) to limit the window of exposure if a token is leaked or intercepted; clients exchange their longer-lived `refresh_token` at `POST /auth/refresh` to obtain a fresh access token without forcing the user to re-enter their password.

### 3. Why Brute-Force Rate Limiting Lives on `POST /auth/login` (`429 Too Many Requests`)
`POST /auth/login` is the primary target for credential-stuffing and brute-force password guessing, so throttling clients to **5 failed attempts per 60 seconds per IP** (`429 Too Many Requests` + `Retry-After: 60`) stops automated attacks at the edge before they can guess weak passwords or exhaust upstream Identity Provider quotas.

### 4. What's Inside a JWT & Stateless Logout
Decoding a Supabase JWT payload (e.g., on `jwt.io`) reveals standard claims such as `sub` (user UUID), `email`, `role`, `iat` (issued at), and `exp` (expiration timestamp). Because the JWT header and payload are merely Base64URL-encoded (signed for integrity, **not** encrypted for secrecy), anyone holding the token can read its contents — so secrets must never be placed inside a JWT, and purely stateless JWT checks cannot instantly revoke an already-issued token without querying server-side session state (`supabase.auth.get_user(token)`).
