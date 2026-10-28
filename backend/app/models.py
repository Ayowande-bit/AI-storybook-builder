
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    Float,
)
from sqlalchemy.orm import relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default="user", server_default="user")

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    stories = relationship(
        "Story",
        back_populates="owner",
        cascade="all, delete-orphan",
    )


class SystemSettings(Base):
    __tablename__ = "system_settings"

    id = Column(Integer, primary_key=True)
    application_name = Column(
        String(100),
        nullable=False,
        default="AI Storybook Builder",
    )
    description = Column(
        Text,
        nullable=False,
        default="Create personalized children's storybooks.",
    )
    default_age_range = Column(String(20), nullable=False, default="3-5")
    story_generation_model = Column(
        String(120), nullable=False, default="openai/gpt-oss-120b"
    )
    story_generation_max_tokens = Column(Integer, nullable=False, default=3000)
    story_generation_temperature = Column(Float, nullable=False, default=0.7)
    illustration_model = Column(String(40), nullable=False, default="gpt-image-1")
    illustration_size = Column(String(20), nullable=False, default="1024x1024")
    max_illustrations_per_story = Column(Integer, nullable=False, default=20)
    password_min_length = Column(Integer, nullable=False, default=12)
    access_token_minutes = Column(Integer, nullable=False, default=30)


class Story(Base):
    __tablename__ = "stories"

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    title = Column(String(200), nullable=False)
    prompt = Column(Text, nullable=False)
    content = Column(Text, nullable=False)
    age_range = Column(String(20), nullable=False)

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    owner = relationship("User", back_populates="stories")
    settings = relationship(
        "StorybookSettings",
        back_populates="story",
        cascade="all, delete-orphan",
        uselist=False,
    )
    illustrations = relationship(
        "Illustration",
        back_populates="story",
        cascade="all, delete-orphan",
        order_by="Illustration.created_at",
    )


class StorybookSettings(Base):
    __tablename__ = "storybook_settings"

    id = Column(Integer, primary_key=True, index=True)
    story_id = Column(
        Integer,
        ForeignKey("stories.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    font_family = Column(String(20), nullable=False, default="serif")
    theme = Column(String(20), nullable=False, default="classic")
    page_layout = Column(String(20), nullable=False, default="portrait")

    story = relationship("Story", back_populates="settings")


class Illustration(Base):
    __tablename__ = "illustrations"

    id = Column(Integer, primary_key=True, index=True)
    story_id = Column(
        Integer,
        ForeignKey("stories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    prompt = Column(Text, nullable=False)
    image_data = Column(LargeBinary, nullable=False)
    content_type = Column(String(50), nullable=False, default="image/png")
    page_number = Column(Integer, nullable=False, default=1)
    x = Column(Float, nullable=False, default=10)
    y = Column(Float, nullable=False, default=10)
    width = Column(Float, nullable=False, default=80)
    height = Column(Float, nullable=False, default=80)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    story = relationship("Story", back_populates="illustrations")
