from alembic import context
from sqlalchemy import create_engine

from quest_viewer.config import Settings
from quest_viewer.db.models import Base


def run_migrations():
    engine = create_engine(Settings().database_url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


run_migrations()
