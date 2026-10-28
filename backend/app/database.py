
from pathlib import Path

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import declarative_base, sessionmaker

# Locate the backend directory.
BASE_DIR = Path(__file__).resolve().parents[1]

# Create the SQLite database file inside backend/.
DATABASE_URL = f"sqlite:///{BASE_DIR / 'storybook.db'}"

# Establish the database connection.
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)

# Create a factory for database sessions.
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

# Base class for all database models.
Base = declarative_base()


# Provide a database session to API endpoints.
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_user_role_column():
    if "role" not in {
        column["name"] for column in inspect(engine).get_columns("users")
    }:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "ALTER TABLE users "
                "ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'user'"
            )
