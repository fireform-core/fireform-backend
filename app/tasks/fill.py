import logging
from datetime import datetime, timezone
from urllib.parse import quote
from uuid import UUID

from app.api.schemas.enums import JobStatus
from app.core.celery import celery_app
from app.core.errors.base import AppError
from app.db.database import get_session
from app.db.repositories import get_job_by_celery_id, get_template, update_job
from app.models.models import Profile
from app.services.form import FormService

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="fill_form")
def fill_form_task(
    self,
    template_id: int,
    input_text: str,
    input_id_str: str,
    model: str | None = None,
    provider: str | None = None,
    profile: dict | None = None,
):
    session = next(get_session())
    try:
        job = get_job_by_celery_id(session, self.request.id)
        if not job:
            raise RuntimeError(f"No job row for celery task {self.request.id}")

        job.status = JobStatus.processing
        job.progress_percent = 10
        job.updated_at = datetime.now(timezone.utc)
        update_job(session, job)

        template = get_template(session, template_id)
        if not template:
            raise ValueError(f"Template {template_id} not found")

        submission = FormService().fill_and_persist(
            session, template, input_text, UUID(input_id_str), model, provider,
            profile=Profile(**profile) if profile else None,
        )

        job.status = JobStatus.completed
        job.progress_percent = 100
        job.result_url = (
            f"/api/v1/templates/preview?path={quote(submission.output_pdf_path, safe='')}"
        )
        job.updated_at = datetime.now(timezone.utc)
        update_job(session, job)

        return {"job_id": job.job_id, "result_url": job.result_url}

    except Exception as e:
        if isinstance(e, AppError):
            logger.error("fill_form_task %s failed with %s: %s", self.request.id, e.error_code, e.message)
            error = {"error_code": e.error_code, "message": e.message}
        else:
            logger.exception("fill_form_task %s failed", self.request.id)
            error = {"error_code": "TASK_FAILED", "message": str(e)}
        job = get_job_by_celery_id(session, self.request.id)
        if job:
            job.status = JobStatus.failed
            job.error = error
            job.updated_at = datetime.now(timezone.utc)
            update_job(session, job)
        raise
    finally:
        session.close()
