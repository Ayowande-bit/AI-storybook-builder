
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.routers.auth import get_current_user

router = APIRouter(
    prefix="/api/users",
    tags=["Users"],
)


class UserProfileResponse(BaseModel):
    id: int
    username: str
    email: EmailStr

    model_config = ConfigDict(from_attributes=True)


class UserProfileUpdate(BaseModel):
    username: str | None = Field(default=None, min_length=3, max_length=50)
    email: EmailStr | None = None


@router.get("/me", response_model=UserProfileResponse)
def get_my_profile(
    current_user: User = Depends(get_current_user),
):
    return current_user


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
            detail="Provide at least one field to update.",
        )

    if "username" in changes:
        if changes["username"] is None:
            raise HTTPException(
                status_code=400,
                detail="Username cannot be null.",
            )
        changes["username"] = changes["username"].strip()
        if len(changes["username"]) < 3:
            raise HTTPException(
                status_code=400,
                detail="Username must contain at least 3 characters.",
            )

    if "email" in changes:
        if changes["email"] is None:
            raise HTTPException(
                status_code=400,
                detail="Email cannot be null.",
            )
        changes["email"] = str(changes["email"]).lower()

    conditions = []
    if "username" in changes:
        conditions.append(User.username == changes["username"])
    if "email" in changes:
        conditions.append(User.email == changes["email"])

    if conditions:
        existing_user = db.query(User).filter(
            or_(*conditions)
        ).first()

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
            detail="Could not update your profile.",
        )


@router.delete("/me")
def delete_my_account(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        db.delete(current_user)
        db.commit()
        return {"message": "Account deleted successfully."}
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not delete your account.",
        )

