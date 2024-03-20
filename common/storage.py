from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from bot.models import Base
from logger import logger
from utils import singleton


@singleton
class Storage:
    def __init__(self, db_name: str):
        self.engine = create_engine(db_name)
        self.session = sessionmaker(bind=self.engine)()
        try:
            Base.metadata.create_all(self.engine)
        except Exception as e:
            logger.exception(f"An error occurred while creating tables: {e}")

    async def close(self) -> None:
        self.session.close()
