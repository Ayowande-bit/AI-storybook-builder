
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.routers.auth import get_current_user


# Create the router. main.py imports this exact variable.
router = APIRouter(
    prefix="/api/users",
    tags=["Users"],
)


# -------------------------------
# PROFILE RESPONSE
# -------------------------------

class UserProfileResponse(BaseModel):
    id: int
    username: str
    email: EmailStr

    model_config = ConfigDict(from_attributes=True)


# -------------------------------
# PROFILE UPDATE REQUEST
# -------------------------------

class UserProfileUpdate(BaseModel):
    username: str | None = Field(
        default=None,
        min_length=3,
        max_length=50,
    )
    email: EmailStr | None = None

    @field_validator("username")
    @classmethod
    def validate_username(cls, value):
        if value is not None:
            value = value.strip()

            if len(value) < 3:
                raise ValueError(
                    "Username must contain at least 3 characters."
                )

        return value


# -------------------------------
# GET MY PROFILE
# GET /api/users/me
# -------------------------------

@router.get("/me", response_model=UserProfileResponse)
def get_my_profile(
    current_user: User = Depends(get_current_user),
):
    return current_user


# -------------------------------
# UPDATE MY PROFILE
# PATCH /api/users/me
# -------------------------------

@router.patch("/me", response_model=UserProfileResponse)
def update_my_profile(
    request: UserProfileUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    changes = request.model_dump(exclude_unset=True)

    if not changes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide a username or email to update.",
        )

    if "username" in changes:
        username = changes["username"]

        if username is None:
            raise HTTPException(
                status_code=400,
                detail="Username cannot be null.",
            )

        username = username.strip()

        if len(username) < 3:
            raise HTTPException(
                status_code=400,
                detail="Username must contain at least 3 characters.",
            )

        changes["username"] = username

    if "email" in changes:
        email = changes["email"]

        if email is None:
            raise HTTPException(
                status_code=400,
                detail="Email cannot be null.",
            )

        changes["email"] = str(email).strip().lower()

    # Prevent changing to another user's username or email.
    conditions = []

    if "username" in changes:
        conditions.append(
            User.username.ilike(changes["username"])
        )

    if "email" in changes:
        conditions.append(
            User.email.ilike(changes["email"])
        )

    existing_user = (
        db.query(User)
        .filter(or_(*conditions))
        .first()
    )

    if existing_user and existing_user.id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That username or email is already in use.",
        )

    try:
        for field, value in changes.items():
            setattr(current_user, field, value)

        db.commit()
        db.refresh(current_user)

        return current_user

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
            detail="Unable to update your profile right now.",
        )


# -------------------------------
# DELETE MY ACCOUNT
# DELETE /api/users/me
# -------------------------------

@router.delete("/me")
def delete_my_account(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        db.delete(current_user)
        db.commit()

        return {
            "message": "Your account has been deleted successfully."
        }

    except SQLAlchemyError:
        db.rollback()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to delete your account right now.",
        )
