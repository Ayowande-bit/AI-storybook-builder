import os

from sqlalchemy.orm import Session

from app.models import SystemSettings


def get_system_settings(db: Session) -> SystemSettings:
    settings = db.query(SystemSettings).filter(SystemSettings.id == 1).first()
    if settings is None:
        settings = SystemSettings(
            id=1,
            story_generation_model=os.getenv(
                "GROQ_MODEL", "openai/gpt-oss-120b"
            ),
        )
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings
