from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import sessionmaker

from scanger.config import database_url

_engine: Engine | None = None
_factory: sessionmaker[OrmSession] | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(database_url(), pool_pre_ping=True)
    return _engine


def get_session_factory() -> sessionmaker[OrmSession]:
    global _factory
    if _factory is None:
        _factory = sessionmaker(get_engine(), expire_on_commit=False)
    return _factory
