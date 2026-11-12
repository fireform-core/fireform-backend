import datetime
import logging
import os
import sqlite3
import tempfile
from pathlib import Path

from alembic.config import Config
from alembic.util import CommandError
from sqlmodel import Session, select, text

from alembic import command
from app.core.config import BASE_DIR, FIREFORM_DESKTOP, SEED_TEMPLATE_PDF_PATH
from app.db.database import engine
from app.models import Template

logger = logging.getLogger(__name__)

ALEMBIC_INI = str(BASE_DIR / "alembic.ini")


def _alembic_cfg() -> Config:
    cfg = Config(ALEMBIC_INI)
    # Always resolve script_location from BASE_DIR so migrations work regardless
    # of the process cwd (critical when launched as a PyInstaller binary).
    cfg.set_main_option("script_location", str(BASE_DIR / "alembic"))
    cfg.attributes["configure_logger"] = False
    return cfg


def _sqlite_database_path() -> Path | None:
    if engine.dialect.name != "sqlite":
        return None
    database = engine.url.database
    if not database or database == ":memory:":
        return None
    return Path(database).resolve()


def _backup_sqlite_database(database_path: Path) -> Path:
    fd, backup_name = tempfile.mkstemp(
        prefix=f".{database_path.name}.pre-migration-",
        suffix=".bak",
        dir=database_path.parent,
    )
    os.close(fd)
    backup_path = Path(backup_name)
    try:
        with sqlite3.connect(database_path) as source, sqlite3.connect(backup_path) as target:
            source.backup(target)
    except Exception:
        backup_path.unlink(missing_ok=True)
        raise
    return backup_path


def _restore_sqlite_database(database_path: Path, backup_path: Path) -> None:
    engine.dispose()
    with sqlite3.connect(backup_path) as source, sqlite3.connect(database_path) as target:
        source.backup(target)


def run_migrations():
    logger.info("Running Alembic migrations...")
    backup_path = None
    database_path = _sqlite_database_path() if FIREFORM_DESKTOP else None
    if database_path is not None and database_path.is_file():
        backup_path = _backup_sqlite_database(database_path)

    try:
        command.upgrade(_alembic_cfg(), "head")
    except BaseException as migration_error:
        if backup_path is not None and database_path is not None:
            try:
                _restore_sqlite_database(database_path, backup_path)
            except Exception as restore_error:
                logger.exception("Failed to restore SQLite database after migration failure.")
                raise RuntimeError(
                    "Database migration failed and automatic restore also failed. "
                    f"The pre-migration backup is preserved at {backup_path}."
                ) from restore_error
            backup_path.unlink(missing_ok=True)
        if isinstance(migration_error, CommandError) and "Can't locate revision" in str(migration_error):
            # Exit non-zero with a readable message instead of a bare stack trace.
            raise SystemExit(
                f"[init_db] {migration_error}.\n"
                "The database is stamped with a migration revision this code does not know\n"
                "(e.g. a DB created by another branch). Either reset the dev database:\n"
                "    make down && docker volume rm dev_postgres_data\n"
                "or re-stamp it to a revision in alembic/versions/:\n"
                "    alembic stamp <revision>"
            ) from migration_error
        raise
    else:
        if backup_path is not None:
            backup_path.unlink(missing_ok=True)
    logger.info("Migrations complete.")


def seed_db():
    with Session(engine) as session:
        statement = select(Template)
        try:
            results = session.exec(statement).first()
        except Exception:
            results = None

        if not results:
            logger.info("Seeding database with default template...")
            fields = {
                "Employee's name": "string",
                "Employee's job title": "string",
                "Employee's department supervisor": "string",
                "Employee's phone number": "string",
                "Employee's email": "string",
                "Signature": "string",
                "Date": "string",
            }

            default_template = Template(
                id=2,
                name="Manual Test Template",
                description=(
                    "Employee contact and sign-off form used to manually verify that "
                    "FireForm fills a PDF correctly. Captures who completed the form, "
                    "their contact details, and their signature."
                ),
                fields=fields,
                pdf_path=SEED_TEMPLATE_PDF_PATH,
                created_at=datetime.datetime.now(datetime.timezone.utc),
            )
            session.add(default_template)
            session.commit()
            logger.info("Database seeded successfully.")


def sync_template_id_sequence():
    # The seed row sets its id explicitly, which does not advance Postgres'
    # SERIAL sequence, so the next created template would collide with it.
    # Only ever moves the sequence forward (this runs on every start), so ids
    # of deleted templates are not handed out again.
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as conn:
        conn.execute(text(
            "SELECT setval(pg_get_serial_sequence('template', 'id'), GREATEST("
            "COALESCE((SELECT MAX(id) FROM template), 0) + 1, "
            "nextval(pg_get_serial_sequence('template', 'id'))), false)"
        ))


def init_db():
    run_migrations()
    seed_db()
    sync_template_id_sequence()


if __name__ == "__main__":
    init_db()
