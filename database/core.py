from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from config import DB_PATH

# Create the database engine
engine = create_engine(DB_PATH, echo=False)

# Create a Session factory
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

# Base class for models
Base = declarative_base()

def get_db():
    """Dependency to get a DB session in handlers."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    """Creates tables in the database."""
    Base.metadata.create_all(bind=engine)
