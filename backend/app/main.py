
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from groq import Groq
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import Base, SessionLocal, engine, ensure_user_role_column, get_db
from app.models import Story, User
from app.routers.auth import get_current_user, router as auth_router
from app.routers.admin import router as admin_router
from app.routers.illustrations import router as illustrations_router
from app.routers.stories import router as stories_router
from app.routers.users import router as users_router
from app.system_settings import get_system_settings


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

logger = logging.getLogger(__name__)

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path=ENV_FILE)

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

SYSTEM_PROMPT = """
You are an expert children's storybook writer.

Write original, engaging, complete stories suitable for the
requested age range.

Every story must:
- Have a creative, appropriate title.
- Have a clear beginning, middle, and satisfying ending.
- Include engaging characters and a meaningful plot.
- Use language suitable for the requested age group.
- Include a positive moral lesson.
- Avoid graphic violence, sexual content, dangerous
  instructions, and frightening details.

Return valid JSON with exactly these fields:
{
  "title": "The story title",
  "story": "The complete story in multiple paragraphs",
  "lesson": "The positive lesson learned"
}

The story must be complete, not an outline or summary.
"""


# --------------------------------------------------
# REQUEST SCHEMA
# --------------------------------------------------

class StoryRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=1000)
    age_range: str | None = Field(default=None, min_length=1, max_length=20)


# --------------------------------------------------
# DATABASE LIFESPAN
# --------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_user_role_column()
    with SessionLocal() as db:
        settings = get_system_settings(db)
        app.title = settings.application_name
        app.description = settings.description
    admin_email = os.getenv("ADMIN_EMAIL", "").strip().lower()
    if admin_email:
        with SessionLocal() as db:
            admin_user = db.query(User).filter(
                User.email.ilike(admin_email)
            ).first()
            if admin_user is None:
                logger.warning(
                    "ADMIN_EMAIL does not match a registered user; "
                    "no administrator was bootstrapped."
                )
            elif admin_user.role != "admin":
                admin_user.role = "admin"
                db.commit()
    yield


# --------------------------------------------------
# FASTAPI APPLICATION
# --------------------------------------------------

app = FastAPI(
    title="AI Storybook Builder API",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------
# EXISTING ROUTERS
# --------------------------------------------------

app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(users_router)
app.include_router(stories_router)
app.include_router(illustrations_router)


# --------------------------------------------------
# HEALTH AND INFORMATION ENDPOINTS
# --------------------------------------------------

@app.get("/")
def root(db: Session = Depends(get_db)):
    settings = get_system_settings(db)
    return {
        "message": f"Welcome to {settings.application_name}",
        "description": settings.description,
        "docs": "/docs",
    }


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "AI Storybook Builder API",
    }


@app.get("/api/info")
def api_info(db: Session = Depends(get_db)):
    settings = get_system_settings(db)
    return {
        "name": settings.application_name,
        "description": settings.description,
        "version": "0.2.0",
        "features": [
            "AI story generation",
            "User authentication",
            "Story management",
            "Character illustrations",
            "PDF storybooks",
        ],
        "status": "under development",
    }


# --------------------------------------------------
# SHARED AI STORY GENERATION FUNCTION
# --------------------------------------------------

def generate_story_content(request: StoryRequest, db: Session) -> dict:
    """
    Generate and validate a complete story using Groq.
    This function does not save anything to the database.
    """

    if groq_client is None:
        raise HTTPException(
            status_code=503,
            detail="The story generator is not configured. "
                   "Set GROQ_API_KEY in your .env file.",
        )

    settings = get_system_settings(db)
    age_range = request.age_range or settings.default_age_range

    try:
        response = groq_client.chat.completions.create(
            model=settings.story_generation_model,
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": (
                        f"Write a complete children's story for "
                        f"ages {age_range}.\n"
                        f"Story idea: {request.prompt}\n\n"
                        "Return the requested JSON object. "
                        "Make the story detailed, engaging, "
                        "and suitable for the age group."
                    ),
                },
            ],
            response_format={"type": "json_object"},
            max_tokens=settings.story_generation_max_tokens,
            temperature=settings.story_generation_temperature,
        )

    except Exception:
        logger.exception("Groq API call failed")
        raise HTTPException(
            status_code=502,
            detail="Story generation failed. Please try again.",
        )

    choice = response.choices[0]

    if choice.finish_reason == "length":
        raise HTTPException(
            status_code=502,
            detail="The generated story was cut off. Please try again.",
        )

    raw = choice.message.content or ""

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.error("Groq returned invalid JSON: %r", raw[:500])
        raise HTTPException(
            status_code=502,
            detail="The AI returned an unreadable story.",
        )

    title = str(data.get("title", "")).strip()
    story_text = str(data.get("story", "")).strip()
    lesson = str(data.get("lesson", "")).strip()

    if not title or not story_text or not lesson:
        raise HTTPException(
            status_code=502,
            detail="The AI returned an incomplete story.",
        )

    if len(title) > 200 or len(story_text) + len(lesson) > 49900:
        raise HTTPException(
            status_code=502,
            detail="The generated story exceeds the allowed length.",
        )

    content = f"{story_text}\n\nLesson: {lesson}"

    return {
        "title": title,
        "story": story_text,
        "lesson": lesson,
        "content": content,
        "prompt": request.prompt,
        "age_range": age_range,
        "status": "ready",
    }


# --------------------------------------------------
# GENERATE A STORY WITHOUT SAVING IT
# POST /api/story-request
# --------------------------------------------------

@app.post("/api/story-request")
def create_story_request(
    request: StoryRequest,
    db: Session = Depends(get_db),
):
    """
    Generate a story and return it without saving it.
    """

    generated = generate_story_content(request, db)

    return {
        "title": generated["title"],
        "story": generated["story"],
        "lesson": generated["lesson"],
        "message": generated["story"],
        "prompt": generated["prompt"],
        "age_range": generated["age_range"],
        "status": generated["status"],
    }


# --------------------------------------------------
# GENERATE AND SAVE A STORY
# POST /api/stories/generate
# --------------------------------------------------

@app.post("/api/stories/generate", status_code=201)
def generate_and_save_story(
    request: StoryRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Generate a complete story with AI and save it
    to the database for the authenticated user.
    """

    generated = generate_story_content(request, db)

    story = Story(
        user_id=current_user.id,
        title=generated["title"],
        prompt=generated["prompt"],
        content=generated["content"],
        age_range=generated["age_range"],
    )

    try:
        db.add(story)
        db.commit()
        db.refresh(story)

        return {
            "id": story.id,
            "user_id": story.user_id,
            "title": story.title,
            "prompt": story.prompt,
            "content": story.content,
            "age_range": story.age_range,
            "created_at": story.created_at,
            "settings": {
                "font_family": "serif",
                "theme": "classic",
                "page_layout": "portrait",
            },
        }

    except SQLAlchemyError:
        db.rollback()
        logger.exception("Could not save the generated story")

        raise HTTPException(
            status_code=500,
            detail="The generated story could not be saved.",
        )

    finally:
        db.close()
