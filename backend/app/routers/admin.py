import os
import secrets
from dotenv import load_dotenv
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import Story, User
from app.routers.auth import get_current_user
from app.schemas import (
    StoryResponse,
    TokenResponse,
    UserLogin,
    UserRegister,
)
from app.security import create_access_token, hash_password, verify_password
from app.system_settings import get_system_settings

router = APIRouter(prefix="/api/admin", tags=["Admin"])
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(dotenv_path=ENV_FILE)


class AdminUserResponse(BaseModel):
    id: int
    username: str
    email: EmailStr
    role: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AdminDashboardResponse(BaseModel):
    total_users: int
    total_stories: int
    users_created_last_7_days: int
    stories_created_last_7_days: int


class SystemSettingsResponse(BaseModel):
    application_name: str
    description: str
    default_age_range: str
    story_generation_model: str
    story_generation_max_tokens: int
    story_generation_temperature: float
    illustration_model: str
    illustration_size: str
    max_illustrations_per_story: int

    model_config = ConfigDict(from_attributes=True)


class SystemSettingsUpdate(BaseModel):
    application_name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=1000)
    default_age_range: str = Field(min_length=1, max_length=20)
    story_generation_model: str = Field(min_length=1, max_length=120)
    story_generation_max_tokens: int = Field(ge=256, le=8192)
    story_generation_temperature: float = Field(ge=0, le=2)
    illustration_model: Literal["gpt-image-1", "gpt-image-1-mini"]
    illustration_size: Literal["1024x1024", "1536x1024", "1024x1536"]
    max_illustrations_per_story: int = Field(ge=0, le=100)

    @field_validator(
        "application_name",
        "description",
        "default_age_range",
        "story_generation_model",
    )
    @classmethod
    def validate_nonblank_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be empty.")
        return value


class AdminProfileUpdate(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    email: EmailStr

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Username cannot be empty.")
        return value


class AdminPasswordUpdate(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=1, max_length=128)


class SecuritySettingsResponse(BaseModel):
    password_min_length: int
    access_token_minutes: int

    model_config = ConfigDict(from_attributes=True)


class SecuritySettingsUpdate(BaseModel):
    password_min_length: int = Field(ge=12, le=64)
    access_token_minutes: int = Field(ge=5, le=1440)


@router.post(
    "/register",
    response_model=AdminUserResponse,
    status_code=status.HTTP_201_CREATED,
)
def register_admin(
    request: UserRegister,
    setup_token: str | None = Header(default=None, alias="X-Admin-Setup-Token"),
    db: Session = Depends(get_db),
):
    configured_token = os.getenv("ADMIN_SETUP_TOKEN")
    if not configured_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Administrator registration is not configured.",
        )
    if setup_token is None or not secrets.compare_digest(
        setup_token.encode("utf-8"),
        configured_token.encode("utf-8"),
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid administrator setup credential.",
        )

    settings = get_system_settings(db)
    if len(request.password) < settings.password_min_length:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "Password must contain at least "
                f"{settings.password_min_length} characters."
            ),
        )

    username = request.username.strip()
    email = str(request.email).strip().lower()
    existing_user = db.query(User).filter(
        or_(User.username.ilike(username), User.email.ilike(email))
    ).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That username or email is already registered.",
        )

    admin = User(
        username=username,
        email=email,
        hashed_password=hash_password(request.password),
        role="admin",
    )
    try:
        db.add(admin)
        db.commit()
        db.refresh(admin)
        return admin
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That username or email is already registered.",
        )
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to create the administrator account.",
        )


@router.post("/login", response_model=TokenResponse)
def login_admin(
    request: UserLogin,
    db: Session = Depends(get_db),
):
    email = str(request.email).strip().lower()
    admin = db.query(User).filter(User.email.ilike(email)).first()
    if (
        admin is None
        or admin.role != "admin"
        or not verify_password(request.password, admin.hashed_password)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    settings = get_system_settings(db)
    return TokenResponse(
        access_token=create_access_token(
            int(admin.id),
            int(settings.access_token_minutes),
        )
    )


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access required.",
        )
    return current_user


@router.get("/settings", response_model=SystemSettingsResponse)
def get_admin_settings(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    return get_system_settings(db)


@router.put("/settings", response_model=SystemSettingsResponse)
def update_admin_settings(
    request: SystemSettingsUpdate,
    http_request: Request,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    settings = get_system_settings(db)
    for field, value in request.model_dump().items():
        setattr(settings, field, value)
    try:
        db.commit()
        db.refresh(settings)
        http_request.app.title = settings.application_name
        http_request.app.description = settings.description
        http_request.app.openapi_schema = None
        return settings
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not update system settings.",
        )


@router.get("/settings/profile", response_model=AdminUserResponse)
def get_admin_profile(
    current_admin: User = Depends(require_admin),
):
    return current_admin


@router.put("/settings/profile", response_model=AdminUserResponse)
def update_admin_profile(
    request: AdminProfileUpdate,
    db: Session = Depends(get_db),
    current_admin: User = Depends(require_admin),
):
    username = request.username.strip()
    email = str(request.email).strip().lower()
    existing_user = db.query(User).filter(
        or_(User.username.ilike(username), User.email.ilike(email))
    ).first()
    if existing_user is not None and existing_user.id != current_admin.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That username or email is already in use.",
        )
    try:
        current_admin.username = username
        current_admin.email = email
        db.commit()
        db.refresh(current_admin)
        return current_admin
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That username or email is already in use.",
        )
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not update the administrator profile.",
        )


@router.put("/settings/password")
def update_admin_password(
    request: AdminPasswordUpdate,
    db: Session = Depends(get_db),
    current_admin: User = Depends(require_admin),
):
    if not verify_password(request.current_password, current_admin.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect.",
        )
    settings = get_system_settings(db)
    if len(request.new_password) < settings.password_min_length:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "New password must contain at least "
                f"{settings.password_min_length} characters."
            ),
        )
    if verify_password(request.new_password, current_admin.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must differ from the current password.",
        )
    try:
        current_admin.hashed_password = hash_password(request.new_password)
        db.commit()
        return {"message": "Administrator password updated successfully."}
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not update the administrator password.",
        )


@router.get("/settings/security", response_model=SecuritySettingsResponse)
def get_security_settings(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    return get_system_settings(db)


@router.put("/settings/security", response_model=SecuritySettingsResponse)
def update_security_settings(
    request: SecuritySettingsUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    settings = get_system_settings(db)
    settings.password_min_length = request.password_min_length
    settings.access_token_minutes = request.access_token_minutes
    try:
        db.commit()
        db.refresh(settings)
        return settings
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not update security settings.",
        )


@router.get("/dashboard", response_model=AdminDashboardResponse)
def get_admin_dashboard(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    recent_cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    return {
        "total_users": db.query(User).count(),
        "total_stories": db.query(Story).count(),
        "users_created_last_7_days": db.query(User).filter(
            User.created_at >= recent_cutoff
        ).count(),
        "stories_created_last_7_days": db.query(Story).filter(
            Story.created_at >= recent_cutoff
        ).count(),
    }


@router.get("/users", response_model=list[AdminUserResponse])
def list_users(
    q: str | None = Query(default=None, min_length=1, max_length=255),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    query = db.query(User)
    if q is not None:
        search = f"%{q.strip()}%"
        query = query.filter(
            or_(User.username.ilike(search), User.email.ilike(search))
        )
    return (
        query.order_by(User.created_at.desc(), User.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


@router.get("/users/{user_id}", response_model=AdminUserResponse)
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )
    return user


@router.get("/stories", response_model=list[StoryResponse])
def list_stories(
    q: str | None = Query(default=None, min_length=1, max_length=200),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    query = db.query(Story).options(joinedload(Story.settings))
    if q is not None:
        query = query.filter(Story.title.ilike(f"%{q.strip()}%"))
    return (
        query.order_by(Story.created_at.desc(), Story.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


@router.get("/stories/{story_id}", response_model=StoryResponse)
def get_story(
    story_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    story = (
        db.query(Story)
        .options(joinedload(Story.settings))
        .filter(Story.id == story_id)
        .first()
    )
    if story is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Story not found.",
        )
    return story
