from pathlib import Path

from fastapi import HTTPException

from app.core.config import BASE_DIR, DATA_DIR, DEFAULT_TEMPLATE_DIR

PROJECT_ROOT = BASE_DIR


def _is_allowed_path(candidate: Path) -> bool:
    allowed = (PROJECT_ROOT, DATA_DIR)
    return any(candidate == root or root in candidate.parents for root in allowed)


def _resolve_target_directory(directory: str) -> Path:
    dir_value = (directory or DEFAULT_TEMPLATE_DIR).strip()
    if not dir_value:
        raise HTTPException(status_code=400, detail="Directory is required.")

    candidate = Path(dir_value)
    if not candidate.is_absolute():
        candidate = (PROJECT_ROOT / candidate).resolve()
    else:
        candidate = candidate.resolve()

    if not _is_allowed_path(candidate):
        raise HTTPException(status_code=400, detail="Directory must be inside the project or data directory.")

    return candidate


def make_storable_path(path: Path) -> str:
    """Return a path as a posix string suitable for DB storage.

    When ``path`` is inside PROJECT_ROOT we store a project-relative string so
    submissions are portable across machines and docker volume mounts (the
    historical behaviour for server/Docker deployments).

    When ``path`` is *outside* PROJECT_ROOT — which happens in desktop mode
    where DATA_DIR lives in ``~/Library/Application Support/FireForm/data/``
    rather than under ``sys._MEIPASS`` — we fall back to the absolute posix
    path.  ``_resolve_project_file`` already allows absolute paths that are
    inside DATA_DIR, so the round-trip still resolves correctly.
    """
    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _resolve_project_file(file_path: str) -> Path:
    raw_path = (file_path or "").strip()
    if not raw_path:
        raise HTTPException(status_code=400, detail="Path is required.")

    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = (PROJECT_ROOT / candidate).resolve()
    else:
        candidate = candidate.resolve()

    if not _is_allowed_path(candidate):
        raise HTTPException(status_code=400, detail="Path must be inside the project or data directory.")

    return candidate
