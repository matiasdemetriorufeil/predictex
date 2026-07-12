import logging

from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from src.config import Settings
from src.exceptions import ConfigurationError

logger = logging.getLogger(__name__)

engine = create_engine(Settings().database_url)

SessionLocal = sessionmaker(bind=engine)


def get_session() -> Session:
    logger.debug("Creating new database session")
    session = SessionLocal()
    try:
        session.connection()
    except SQLAlchemyError as exc:
        session.close()
        logger.error("Failed to connect to the database", exc_info=True)
        raise ConfigurationError(
            "Could not establish a database connection",
            context={"database_url": engine.url.render_as_string(hide_password=True)},
        ) from exc
    return session
