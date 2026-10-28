from io import BytesIO
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import landscape, portrait
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Flowable, PageBreak, Paragraph, SimpleDocTemplate, Spacer
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.database import get_db
from app.models import Illustration, Story, StorybookSettings, User
from app.routers.auth import get_current_user
from app.schemas import (
    StoryCreate,
    StoryResponse,
    StorySettingsResponse,
    StorySettingsUpdate,
    StoryUpdate,
)

router = APIRouter(prefix="/api", tags=["Stories"])

DEFAULT_SETTINGS = {
    "font_family": "serif",
    "theme": "classic",
    "page_layout": "portrait",
}

PDF_THEMES = {
    "classic": (colors.HexColor("#243447"), colors.HexColor("#ffffff")),
    "bedtime": (colors.HexColor("#f4e8ff"), colors.HexColor("#211735")),
    "adventure": (colors.HexColor("#e8f4df"), colors.HexColor("#18351f")),
}
PDF_FONTS = {
    "serif": "Times-Roman",
    "sans-serif": "Helvetica",
}
PDF_PAGE_SIZES = {
    "portrait": portrait((8.5 * inch, 11 * inch)),
    "landscape": landscape((8.5 * inch, 11 * inch)),
    "square": (8.5 * inch, 8.5 * inch),
}


class IllustrationLayoutPage(Flowable):
    def __init__(self, page_number: int, illustrations: list[Illustration]):
        super().__init__()
        self.page_number = page_number
        self.illustrations = illustrations

    def wrap(self, available_width, available_height):
        self.width = available_width
        self.height = available_height
        return self.width, self.height

    def draw(self):
        self.canv.setFont("Helvetica-Bold", 12)
        self.canv.drawCentredString(
            self.width / 2,
            self.height - 12,
            f"Illustration page {self.page_number}",
        )
        for illustration in self.illustrations:
            x = self.width * illustration.x / 100
            y = self.height * (100 - illustration.y - illustration.height) / 100
            width = self.width * illustration.width / 100
            height = self.height * illustration.height / 100
            self.canv.drawImage(
                ImageReader(BytesIO(illustration.image_data)),
                x,
                y,
                width=width,
                height=height,
                preserveAspectRatio=True,
                anchor="c",
                mask="auto",
            )


def _owned_story(db: Session, story_id: int, user_id: int) -> Story:
    story = (
        db.query(Story)
        .options(joinedload(Story.settings))
        .filter(Story.id == story_id, Story.user_id == user_id)
        .first()
    )
    if story is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Story not found.",
        )
    return story


def _story_response(story: Story) -> dict:
    settings = story.settings
    return {
        "id": story.id,
        "user_id": story.user_id,
        "title": story.title,
        "prompt": story.prompt,
        "content": story.content,
        "age_range": story.age_range,
        "created_at": story.created_at,
        "settings": settings or DEFAULT_SETTINGS,
    }


@router.post(
    "/stories",
    response_model=StoryResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_story(
    request: StoryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    story = Story(user_id=current_user.id, **request.model_dump())
    try:
        db.add(story)
        db.commit()
        db.refresh(story)
        return _story_response(story)
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not save the story.",
        )


@router.get("/stories", response_model=list[StoryResponse])
def list_stories(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stories = (
        db.query(Story)
        .options(joinedload(Story.settings))
        .filter(Story.user_id == current_user.id)
        .order_by(Story.created_at.desc(), Story.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [_story_response(story) for story in stories]


@router.get("/stories/{story_id}", response_model=StoryResponse)
def get_story(
    story_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _story_response(_owned_story(db, story_id, current_user.id))


@router.patch("/stories/{story_id}", response_model=StoryResponse)
def update_story(
    story_id: int,
    request: StoryUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    changes = request.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide at least one field to update.",
        )
    if any(value is None for value in changes.values()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Story fields cannot be null.",
        )

    story = _owned_story(db, story_id, current_user.id)
    try:
        for field, value in changes.items():
            setattr(story, field, value)
        db.commit()
        db.refresh(story)
        return _story_response(story)
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not update the story.",
        )


@router.delete("/stories/{story_id}")
def delete_story(
    story_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    story = (
        db.query(Story)
        .options(
            joinedload(Story.settings),
            selectinload(Story.illustrations),
        )
        .filter(Story.id == story_id, Story.user_id == current_user.id)
        .first()
    )
    if story is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Story not found.",
        )
    try:
        db.delete(story)
        db.commit()
        return {"message": "Story deleted successfully."}
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not delete the story.",
        )


@router.patch(
    "/stories/{story_id}/settings",
    response_model=StorySettingsResponse,
)
def update_story_settings(
    story_id: int,
    request: StorySettingsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    changes = request.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide at least one setting to update.",
        )
    if any(value is None for value in changes.values()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Story settings cannot be null.",
        )

    story = _owned_story(db, story_id, current_user.id)
    settings = story.settings
    try:
        if settings is None:
            settings = StorybookSettings(story_id=story.id, **DEFAULT_SETTINGS)
            db.add(settings)
        for field, value in changes.items():
            setattr(settings, field, value)
        db.commit()
        db.refresh(settings)
        return settings
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not update storybook settings.",
        )


@router.get("/stories/{story_id}/pdf")
def export_story_pdf(
    story_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    story = (
        db.query(Story)
        .options(
            joinedload(Story.settings),
            selectinload(Story.illustrations),
        )
        .filter(Story.id == story_id, Story.user_id == current_user.id)
        .first()
    )
    if story is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Story not found.",
        )
    settings = story.settings
    theme = settings.theme if settings else DEFAULT_SETTINGS["theme"]
    font_family = settings.font_family if settings else DEFAULT_SETTINGS["font_family"]
    page_layout = settings.page_layout if settings else DEFAULT_SETTINGS["page_layout"]
    title_color, background = PDF_THEMES[theme]
    font = PDF_FONTS[font_family]
    output = BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=PDF_PAGE_SIZES[page_layout],
        rightMargin=0.7 * inch,
        leftMargin=0.7 * inch,
        topMargin=0.7 * inch,
        bottomMargin=0.7 * inch,
        title=story.title,
        author="AI Storybook Builder",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "StoryTitle",
        parent=styles["Title"],
        fontName=font,
        fontSize=26,
        leading=31,
        textColor=title_color,
        alignment=TA_CENTER,
        spaceAfter=20,
    )
    body_style = ParagraphStyle(
        "StoryBody",
        parent=styles["BodyText"],
        fontName=font,
        fontSize=13,
        leading=19,
        textColor=title_color,
        spaceAfter=12,
    )
    story_flow = [
        Paragraph(escape(story.title), title_style),
        Paragraph(f"For ages {escape(story.age_range)}", body_style),
        Spacer(1, 0.3 * inch),
    ]

    for paragraph in story.content.splitlines():
        text = paragraph.strip()
        if text:
            story_flow.append(Paragraph(escape(text), body_style))

    if story.illustrations:
        illustration_pages: dict[int, list[Illustration]] = {}
        for illustration in story.illustrations:
            illustration_pages.setdefault(illustration.page_number, []).append(
                illustration
            )
        for page_number in sorted(illustration_pages):
            story_flow.extend(
                [
                    PageBreak(),
                    IllustrationLayoutPage(
                        page_number,
                        illustration_pages[page_number],
                    ),
                ]
            )

    def paint_page(canvas, _document):
        canvas.saveState()
        canvas.setFillColor(background)
        canvas.rect(0, 0, *document.pagesize, fill=1, stroke=0)
        canvas.restoreState()

    try:
        document.build(story_flow, onFirstPage=paint_page, onLaterPages=paint_page)
    except (OSError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not generate the storybook PDF.",
        )

    return Response(
        content=output.getvalue(),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="storybook-{story.id}.pdf"'
        },
    )
