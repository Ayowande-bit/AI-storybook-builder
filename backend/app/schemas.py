
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class UserRegister(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Username cannot be empty.")
        return value


class UserLogin(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserResponse(BaseModel):
    id: int
    username: str
    email: EmailStr

    model_config = ConfigDict(from_attributes=True)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MessageResponse(BaseModel):
    message: str



    
class StoryCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    prompt: str = Field(min_length=3, max_length=5000)
    content: str = Field(min_length=1, max_length=50000)
    age_range: str = Field(default="3-5", min_length=1, max_length=20)

    @field_validator("title", "prompt", "content", "age_range")
    @classmethod
    def validate_story_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be empty.")
        return value


class StoryUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    prompt: str | None = Field(default=None, min_length=3, max_length=5000)
    content: str | None = Field(default=None, min_length=1, max_length=50000)
    age_range: str | None = Field(default=None, min_length=1, max_length=20)

    @field_validator("title", "prompt", "content", "age_range")
    @classmethod
    def validate_story_text(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be empty.")
        return value


class StorySettingsUpdate(BaseModel):
    font_family: Literal["serif", "sans-serif"] | None = None
    theme: Literal["classic", "bedtime", "adventure"] | None = None
    page_layout: Literal["portrait", "landscape", "square"] | None = None


class StorySettingsResponse(BaseModel):
    font_family: Literal["serif", "sans-serif"]
    theme: Literal["classic", "bedtime", "adventure"]
    page_layout: Literal["portrait", "landscape", "square"]

    model_config = ConfigDict(from_attributes=True)


class StoryResponse(BaseModel):
    id: int
    user_id: int
    title: str
    prompt: str
    content: str
    age_range: str
    created_at: datetime
    settings: StorySettingsResponse | None = None

    model_config = ConfigDict(from_attributes=True)


class IllustrationCreate(BaseModel):
    prompt: str = Field(min_length=3, max_length=4000)

    @field_validator("prompt")
    @classmethod
    def validate_prompt(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Prompt cannot be empty.")
        return value


class IllustrationPlacementUpdate(BaseModel):
    page_number: int | None = Field(default=None, ge=1)
    x: float | None = Field(default=None, ge=0, le=100)
    y: float | None = Field(default=None, ge=0, le=100)
    width: float | None = Field(default=None, gt=0, le=100)
    height: float | None = Field(default=None, gt=0, le=100)


class IllustrationResponse(BaseModel):
    id: int
    story_id: int
    prompt: str
    content_type: str
    image_url: str
    page_number: int
    x: float
    y: float
    width: float
    height: float
    created_at: datetime
