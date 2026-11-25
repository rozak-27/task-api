import os

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Request, Response, Security
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from supabase import Client, create_client

load_dotenv()

SUPABASE_URL = (os.getenv("SUPABASE_URL") or "").strip().rstrip("/")
SUPABASE_KEY = (os.getenv("SUPABASE_KEY") or "").strip()

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Missing SUPABASE_URL or SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

app = FastAPI(title="AI Rematch Auth API", version="1.0.0")
security = HTTPBearer(auto_error=False)


class Credentials(BaseModel):
    email: str | None = None
    password: str | None = None


@app.exception_handler(RequestValidationError)
async def handle_validation_error(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=400, content={"error": "Bad request: invalid JSON payload"})


def verify_jwt(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Security(security),
):
    raw_header = request.headers.get("Authorization", "")
    scheme, _, token = raw_header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip() or " " in token.strip():
        return None
    try:
        res = supabase.auth.get_user(token.strip())
        return res.user if res and res.user else None
    except Exception:
        return None


def require_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Security(security),
):
    raw_header = request.headers.get("Authorization", "")
    parts = raw_header.split(" ")
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise _AuthError(401, "Access token required")

    try:
        res = supabase.auth.get_user(parts[1].strip())
        if not res or not res.user:
            raise _AuthError(401, "Invalid or expired token")
        return res.user
    except _AuthError:
        raise
    except Exception as exc:
        raise _AuthError(401, "Invalid or expired token") from exc


class _AuthError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message


@app.exception_handler(_AuthError)
async def handle_auth_error(request: Request, exc: _AuthError):
    return JSONResponse(status_code=exc.status_code, content={"error": exc.message})


@app.post("/auth/signup", status_code=201)
def ai_signup(body: Credentials | None = None):
    if not body or not (body.email or "").strip() or not (body.password or ""):
        return JSONResponse(status_code=400, content={"error": "Email and password required"})
    try:
        res = supabase.auth.sign_up({"email": body.email.strip(), "password": body.password})
        if not res.user:
            return JSONResponse(status_code=400, content={"error": "Signup failed"})
        return res.user.model_dump(mode="json")
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.post("/auth/login")
def ai_login(body: Credentials | None = None):
    if not body or not (body.email or "").strip() or not (body.password or ""):
        return JSONResponse(status_code=400, content={"error": "Email and password required"})
    try:
        res = supabase.auth.sign_in_with_password(
            {"email": body.email.strip(), "password": body.password}
        )
        if not res.session:
            return JSONResponse(status_code=401, content={"error": "Invalid login credentials"})
        return {
            "access_token": res.session.access_token,
            "refresh_token": res.session.refresh_token,
        }
    except Exception:
        return JSONResponse(status_code=401, content={"error": "Invalid login credentials"})


@app.post("/auth/logout", status_code=204)
def ai_logout(user=Depends(require_user)):
    try:
        supabase.auth.sign_out()
    except Exception:
        pass
    return Response(status_code=204)


@app.get("/public/info")
def ai_public_info():
    return {"message": "Welcome stranger! This info is public."}


@app.get("/protected/profile")
def ai_profile(user=Depends(require_user)):
    return {
        "id": user.id,
        "email": user.email,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


@app.get("/protected/dashboard")
def ai_dashboard(user=Depends(require_user)):
    return {"message": f"Dashboard for {user.email}", "id": user.id}
