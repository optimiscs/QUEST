from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from quest_viewer.config import Settings


def create_session_factory(settings: Settings):
    engine = create_engine(
        settings.database_url,
        pool_size=settings.pool_size,
        max_overflow=5,
        pool_pre_ping=True,
        hide_parameters=True,
        connect_args={"connect_timeout": 5},
    )
    return engine, sessionmaker(engine, expire_on_commit=False)
