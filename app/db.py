"""SQLite with BEGIN IMMEDIATE: every transaction takes the write lock up front, so the
guard's read-usage-then-reserve step is atomic across threads *and* processes (API + CLI)."""
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def make_engine(url: str):
    if url.startswith("sqlite:///"):
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    eng = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})

    @event.listens_for(eng, "connect")
    def _no_implicit_tx(dbapi_conn, _):
        dbapi_conn.isolation_level = None  # let us issue BEGIN ourselves

    @event.listens_for(eng, "begin")
    def _begin_immediate(conn):
        conn.exec_driver_sql("BEGIN IMMEDIATE")

    return eng


engine = make_engine(get_settings().sqlite_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db(eng=None) -> None:
    import app.models  # noqa: F401

    Base.metadata.create_all(bind=eng or engine)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
