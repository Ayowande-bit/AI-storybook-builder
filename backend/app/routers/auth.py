
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import or_
from sqlalchemy.orm import Session
from jwt.exceptions import InvalidTokenError

from app.database import get_db
from app.models import User
from app.schemas import UserRegister, UserLogin, UserResponse, TokenResponse
from app.security import (
    hash_password,
    verify_password,
    create_access_token,
    decode_access_token,
)
from app.system_settings import get_system_settings

router = APIRouter(prefix="/api/auth", tags=["Authentication"])
bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing authentication token.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if credentials is None:
        raise unauthorized

    try:
        payload = decode_access_token(credentials.credentials)
        user_id = int(payload["sub"])
        if user_id <= 0:
            raise unauthorized
    except (InvalidTokenError, ValueError, KeyError, TypeError):
        raise unauthorized

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise unauthorized

    return user


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
def register_user(
    request: UserRegister,
    db: Session = Depends(get_db),
):
    username = request.username.strip()
    email = str(request.email).strip().lower()
    settings = get_system_settings(db)
    if len(request.password) < settings.password_min_length:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "Password must contain at least "
                f"{settings.password_min_length} characters."
            ),
        )

    existing_user = db.query(User).filter(
        or_(
            User.username.ilike(username),
            User.email.ilike(email),
        )
    ).first()

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That username or email is already registered.",
        )

    user = User(
        username=username,
        email=email,
        hashed_password=hash_password(request.password),
    )

    try:
        db.add(user)
        db.commit()
        db.refresh(user)
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to create your account right now.",
        )

    return user


@router.post("/login", response_model=TokenResponse)
def login_user(
    request: UserLogin,
    db: Session = Depends(get_db),
):
    email = str(request.email).strip().lower()
    user = db.query(User).filter(
        User.email.ilike(email)
    ).first()

    if user is None or not verify_password(
        request.password, user.hashed_password
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    settings = get_system_settings(db)
    token = create_access_token(
        int(user.id),
        int(settings.access_token_minutes),
    )
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserResponse)
def read_current_user(
    current_user: User = Depends(get_current_user),
):
    return current_user
