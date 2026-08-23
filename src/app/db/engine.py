from contextlib import contextmanager
from ..config import get_settings
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine

engine = create_engine(
    f"sqlite:///{get_settings().db_path}",
    connect_args={"check_same_thread": False},
)


# @event.listens_for(Engine, "connect")
# def set_sqlite_pragma(dbapi_connection, connection_record):
#     cursor = dbapi_connection.cursor()
#     cursor.execute("PRAGMA foreign_keys=ON")
#     cursor.close()

@contextmanager
def get_connection():
    with engine.connect() as conn:
        yield conn

