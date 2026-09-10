from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr

from app.core.security import DEMO_USERS, CurrentTenantUser, create_demo_token, get_current_tenant_user

router = APIRouter(prefix="/auth", tags=["Authentication"])


class LoginRequest(BaseModel):
    email: str
    password: str = ""


class SignupRequest(BaseModel):
    name: str
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict[str, Any]


@router.post("/signup", response_model=LoginResponse, status_code=status.HTTP_201_CREATED)
async def signup(req: SignupRequest):
    from uuid import uuid4, UUID
    email = req.email.lower().strip()

    if email in DEMO_USERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An account with this email address already exists. Please sign in.",
        )

    # Security rule: Public signup assigns only the default non-privileged role (VIEWER)
    new_user_id = uuid4()
    org_id = UUID("11111111-1111-1111-1111-111111111111")
    DEMO_USERS[email] = {
        "user_id": new_user_id,
        "email": email,
        "name": req.name.strip(),
        "organization_id": org_id,
        "role_name": "VIEWER",
        "password": req.password,
        "permissions": [
            "project.read",
            "task.read",
            "ticket.read",
            "calendar.read",
            "risk.read",
        ],
    }

    token = create_demo_token(email)
    user_info = DEMO_USERS[email]

    return LoginResponse(
        access_token=token,
        user={
            "user_id": str(user_info["user_id"]),
            "email": user_info["email"],
            "name": user_info["name"],
            "organization_id": str(user_info["organization_id"]),
            "role": user_info["role_name"],
            "permissions": user_info["permissions"],
        },
    )


@router.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest):
    email = req.email.lower().strip()
    if email not in DEMO_USERS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password. Please verify your credentials.",
        )

    # Validate credentials strictly against account-specific assigned password
    expected_password = DEMO_USERS[email].get("password")
    if expected_password:
        if req.password != expected_password:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password. Please verify your credentials.",
            )
    else:
        if req.password not in {"pmrgsolution123", "NextGenBroaDband@123"}:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password. Please verify your credentials.",
            )

    token = create_demo_token(email)
    user_info = DEMO_USERS[email]

    return LoginResponse(
        access_token=token,
        user={
            "user_id": str(user_info["user_id"]),
            "email": user_info["email"],
            "name": user_info.get("name", user_info["email"].split("@")[0].upper()),
            "organization_id": str(user_info["organization_id"]),
            "role": user_info["role_name"],
            "permissions": user_info["permissions"],
        },
    )


@router.get("/me")
async def get_me(user: CurrentTenantUser = Depends(get_current_tenant_user)):
    return {
        "user_id": str(user.user_id),
        "email": user.email,
        "organization_id": str(user.organization_id),
        "role": user.role_name,
        "permissions": user.permissions,
    }


@router.get("/personas")
async def get_personas():
    """Returns all available test and demo personas with their roles and permissions."""
    personas = []
    for email, info in DEMO_USERS.items():
        personas.append({
            "user_id": str(info["user_id"]),
            "email": email,
            "name": info.get("name", email.split("@")[0].capitalize()),
            "organization_id": str(info["organization_id"]),
            "role": info["role_name"],
            "permissions": info["permissions"],
        })
    return personas
