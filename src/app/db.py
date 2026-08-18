from contextlib import contextmanager
from .config import get_settings
from sqlalchemy import create_engine

engine = create_engine(
    f"sqlite:///{get_settings().db_path}",
    connect_args={"check_same_thread": False},
)


@contextmanager
def get_connection():
    with engine.connect() as conn:
        yield conn
