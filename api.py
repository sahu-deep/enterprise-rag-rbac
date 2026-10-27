import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import jwt
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

from rbac import (
    authenticate_user,
    can_access_collection,
    create_first_admin,
    create_user,
    has_users,
    initialize_auth_db,
)
from service.rag_service import query_rag
from service.query_intent import is_employee_count_question
from codebasic_chat import sanitize_pii, is_query_in_scope

load_dotenv()

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
if not JWT_SECRET_KEY:
    raise RuntimeError("JWT_SECRET_KEY is missing from your .env file")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Keep database initialization inside the API, not the Streamlit UI.
    initialize_auth_db()
    yield


app = FastAPI(title="FinSolve RAG API", lifespan=lifespan)
security = HTTPBearer()


class LoginRequest(BaseModel):
    username: str
    password: str


class ChatRequest(BaseModel):
    collection: str
    question: str


class SetupAdminRequest(BaseModel):
    username: str
    full_name: str
    password: str


class CreateUserRequest(BaseModel):
    username: str
    full_name: str
    password: str
    role: str


@app.get("/setup/status")
def setup_status():
    """Tell the UI whether first-run administrator setup is required."""
    return {"setup_required": not has_users()}


@app.post("/setup/admin")
def setup_admin(request: SetupAdminRequest):
    # create_first_admin also checks under a database write lock, protecting
    # against two simultaneous setup requests.
    try:
        user = create_first_admin(
            request.username,
            request.full_name,
            request.password,
        )
        return {
            "message": "Administrator created successfully",
            "username": user["username"],
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/login")
def login(request: LoginRequest):
    user = authenticate_user(request.username, request.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    payload = {
        "sub": user["username"],
        "role": user["role"],
        "is_admin": user["is_admin"],
        "allowed_collections": user["allowed_collections"],
        "exp": datetime.now(timezone.utc) + timedelta(minutes=30),
    }
    token = jwt.encode(payload, JWT_SECRET_KEY, algorithm="HS256")

    return {
        "access_token": token,
        "token_type": "bearer",
        "username": user["username"],
        "full_name": user["full_name"],
        "role": user["role"],
        "is_admin": user["is_admin"],
        "allowed_collections": user["allowed_collections"],
    }


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    try:
        payload = jwt.decode(
            credentials.credentials,
            JWT_SECRET_KEY,
            algorithms=["HS256"],
        )
        return {
            "username": payload["sub"],
            "role": payload["role"],
            "is_admin": payload["is_admin"],
            "allowed_collections": payload["allowed_collections"],
        }
    except (jwt.InvalidTokenError, KeyError):
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token",
        ) from None


@app.post("/admin/users")
def admin_create_user(
    request: CreateUserRequest,
    user: dict = Depends(get_current_user),
):
    if not user.get("is_admin"):
        raise HTTPException(
            status_code=403,
            detail="Administrator access required",
        )

    try:
        create_user(
            request.username,
            request.full_name,
            request.password,
            request.role,
        )
        return {
            "message": "User created successfully",
            "username": request.username.strip(),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/chat")
def chat(
    request: ChatRequest,
    user: dict = Depends(get_current_user),
):
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    if not can_access_collection(user, request.collection):
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to access this collection",
        )

    safe_query = sanitize_pii(request.question)

    try:
        if is_employee_count_question(safe_query):
            if request.collection.casefold() != "hr":
                if not can_access_collection(user, "hr"):
                    raise HTTPException(
                        status_code=403,
                        detail="Employee counts require access to the HR collection.",
                    )
                return {
                    "answer": (
                        "Employee counts are calculated from the HR employee data. "
                        "Select the HR collection and ask again."
                    )
                }

            return {
                "answer": query_rag(
                    query=safe_query,
                    collection=request.collection,
                )
            }

        if not is_query_in_scope(safe_query, request.collection):
            raise HTTPException(
                status_code=400,
                detail="Your question is outside the scope of this department",
            )

        answer = query_rag(query=safe_query, collection=request.collection)
        return {"answer": answer}
    except HTTPException:
        raise
    except Exception as exc:
        # Log the underlying exception server-side if application logging is configured.
        raise HTTPException(
            status_code=500,
            detail="Unable to process your question",
        ) from exc
