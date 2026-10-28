import base64
import binascii
import os

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Illustration, Story, User
from app.routers.auth import get_current_user
from app.schemas import IllustrationCreate, IllustrationPlacementUpdate, IllustrationResponse
from app.system_settings import get_system_settings

router = APIRouter(tags=["Illustrations"])
OPENAI_IMAGES_URL = "https://api.openai.com/v1/images/generations"
MAX_IMAGE_BYTES = 20 * 1024 * 1024


def _illustration_response(illustration: Illustration) -> dict:
    return {
        "id": illustration.id,
        "story_id": illustration.story_id,
        "prompt": illustration.prompt,
        "content_type": illustration.content_type,
        "image_url": f"/api/illustrations/{illustration.id}/image",
        "page_number": illustration.page_number,
        "x": illustration.x,
        "y": illustration.y,
        "width": illustration.width,
        "height": illustration.height,
        "created_at": illustration.created_at,
    }


def _owned_illustration(
    db: Session,
    illustration_id: int,
    user_id: int,
) -> Illustration:
    illustration = (
        db.query(Illustration)
        .join(Story, Story.id == Illustration.story_id)
        .filter(
            Illustration.id == illustration_id,
            Story.user_id == user_id,
        )
        .first()
    )
    if illustration is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Illustration not found.",
        )
    return illustration


@router.post(
    "/api/stories/{story_id}/illustrations",
    response_model=IllustrationResponse,
    status_code=status.HTTP_201_CREATED,
)
def generate_illustration(
    story_id: int,
    request: IllustrationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    story = (
        db.query(Story)
        .filter(Story.id == story_id, Story.user_id == current_user.id)
        .first()
    )
    if story is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Story not found.",
        )

    settings = get_system_settings(db)
    illustration_count = (
        db.query(Illustration)
        .filter(Illustration.story_id == story.id)
        .count()
    )
    if illustration_count >= settings.max_illustrations_per_story:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This story has reached its illustration limit.",
        )

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Illustration generation is not configured. Set OPENAI_API_KEY.",
        )

    prompt = (
        "Create a warm, child-friendly storybook illustration. "
        "Use a gentle, age-appropriate style with no text or lettering. "
        f"Scene description: {request.prompt}"
    )
    try:
        response = httpx.post(
            OPENAI_IMAGES_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": settings.illustration_model,
                "prompt": prompt,
                "size": settings.illustration_size,
                "n": 1,
                "output_format": "png",
            },
            timeout=httpx.Timeout(90.0, connect=10.0),
        )
        response.raise_for_status()
        encoded_image = response.json()["data"][0]["b64_json"]
        if len(encoded_image) > ((MAX_IMAGE_BYTES + 2) // 3) * 4:
            raise ValueError("The generated image is too large.")
        image_data = base64.b64decode(encoded_image, validate=True)
        if not image_data or len(image_data) > MAX_IMAGE_BYTES:
            raise ValueError("The image provider returned an invalid image size.")
        if not image_data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("The image provider returned a non-PNG image.")
    except httpx.HTTPError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The image provider could not generate the illustration.",
        )
    except (ValueError, KeyError, IndexError, TypeError, binascii.Error):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The image provider returned an invalid illustration.",
        )

    illustration = Illustration(
        story_id=story.id,
        prompt=request.prompt,
        image_data=image_data,
        content_type="image/png",
    )
    try:
        db.add(illustration)
        db.commit()
        db.refresh(illustration)
        return _illustration_response(illustration)
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not save the generated illustration.",
        )


@router.get(
    "/api/stories/{story_id}/illustrations",
    response_model=list[IllustrationResponse],
)
def list_illustrations(
    story_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    story = (
        db.query(Story)
        .filter(Story.id == story_id, Story.user_id == current_user.id)
        .first()
    )
    if story is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Story not found.",
        )

    illustrations = (
        db.query(Illustration)
        .filter(Illustration.story_id == story.id)
        .order_by(Illustration.created_at, Illustration.id)
        .all()
    )
    return [_illustration_response(item) for item in illustrations]


@router.get("/api/illustrations/{illustration_id}", response_model=IllustrationResponse)
def get_illustration(
    illustration_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    illustration = _owned_illustration(db, illustration_id, current_user.id)
    return _illustration_response(illustration)


@router.get("/api/illustrations/{illustration_id}/image")
def get_illustration_image(
    illustration_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    illustration = _owned_illustration(db, illustration_id, current_user.id)
    return Response(
        content=illustration.image_data,
        media_type=illustration.content_type,
        headers={"Cache-Control": "private, no-store"},
    )


@router.delete("/api/illustrations/{illustration_id}")
def delete_illustration(
    illustration_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    illustration = _owned_illustration(db, illustration_id, current_user.id)
    try:
        db.delete(illustration)
        db.commit()
        return {"message": "Illustration deleted successfully."}
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not delete the illustration.",
        )


@router.put(
    "/api/stories/{story_id}/illustrations/{illustration_id}",
    response_model=IllustrationResponse,
)
def update_illustration_placement(
    story_id: int,
    illustration_id: int,
    request: IllustrationPlacementUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    illustration = _owned_illustration(db, illustration_id, current_user.id)
    if illustration.story_id != story_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Illustration not found for this story.",
        )

    changes = request.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide at least one placement setting to update.",
        )
    if any(value is None for value in changes.values()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Illustration placement settings cannot be null.",
        )

    placement = {
        "x": changes.get("x", illustration.x),
        "y": changes.get("y", illustration.y),
        "width": changes.get("width", illustration.width),
        "height": changes.get("height", illustration.height),
    }
    if placement["x"] + placement["width"] > 100 or placement["y"] + placement["height"] > 100:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Illustration placement must fit within the page bounds.",
        )

    try:
        for field, value in changes.items():
            setattr(illustration, field, value)
        db.commit()
        db.refresh(illustration)
        return _illustration_response(illustration)
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not update illustration placement.",
        )
