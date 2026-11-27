import logging
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from sqlmodel import Session

from app.api.deps import get_db, verify_api_key
from app.api.middleware.rate_limiter import limiter
from app.api.routes.profiles import get_current_profile
from app.api.schemas.forms import (
    FormFill,
    FormFillResponse,
    FormSubmissionResponse,
    ModelsResponse,
    PurgeResponse,
    TranscriptionResponse,
)
from app.core import paths
from app.core.config import RETENTION_PERIOD_DAYS
from app.core.errors.base import AppError
from app.db.repositories import delete_form_submission, get_form_submission, get_template
from app.models.models import Profile
from app.services import llm
from app.services.form import FormService
from app.services.whisper import call_whisper_asr

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/forms", tags=["forms"])

_MAX_AUDIO_BYTES = 500 * 1024 * 1024  # 500 MB, same as /input/voice


@router.post("/fill", response_model=FormFillResponse)
@limiter.limit("20/minute")
def fill_form(request: Request, form: FormFill, db: Session = Depends(get_db)):
    fetched_template = get_template(db, form.template_id)
    if not fetched_template:
        raise AppError("Template not found", status_code=404, error_code="TEMPLATE_NOT_FOUND")

    svc = FormService()
    try:
        submission = svc.fill_form(
            db,
            template=fetched_template,
            input_id=form.input_id,
            input_text=form.input_text,
            provider=form.provider,
            model=form.model,
            profile_id=form.profile_id,
        )
        return FormFillResponse(
            id=submission.id,
            template_id=submission.template_id,
            profile_id=submission.profile_id,
            input_text=submission.input_text,
            output_pdf_path=submission.output_pdf_path,
        )
    except AppError:
        raise
    except Exception as e:
        # Not an error we know, so keep the traceback
        logger.exception("Form fill for template %s failed", form.template_id)
        raise AppError(str(e), status_code=500, error_code="FORM_FILL_ERROR") from e



@router.get("/models", response_model=ModelsResponse, deprecated=True)
def list_models():
    """The default provider's models. Kept until the frontend moves to
    GET /system/llm/models, which lists every enabled provider."""
    registry = llm.get_registry()
    default = registry.default
    models = [m.name for m in registry.provider_catalog(default.provider).models]

    # Always surface the default, even if the server is down or doesn't list it.
    if default.model not in models:
        models.insert(0, default.model)

    return ModelsResponse(models=models, default=default.model)


@router.post("/transcribe", response_model=TranscriptionResponse)
def transcribe(audio: UploadFile = File(...)):
    """Forward recorded audio to the local Whisper ASR sidecar and return text.

    Mirrors the Ollama wiring: WHISPER_HOST points at the whisper service
    (http://whisper:9000 inside Docker, http://localhost:9000 otherwise). The
    audio is streamed straight through to the local STT service and never
    persisted — no PII leaves the machine.
    """
    if audio.size is not None and audio.size > _MAX_AUDIO_BYTES:
        raise AppError(
            "Audio file exceeds maximum size of 500MB",
            status_code=413,
            error_code="FILE_TOO_LARGE",
            detail={"max_size_bytes": _MAX_AUDIO_BYTES, "received_size_bytes": audio.size},
        )
    content = audio.file.read()
    if len(content) > _MAX_AUDIO_BYTES:
        raise AppError(
            "Audio file exceeds maximum size of 500MB",
            status_code=413,
            error_code="FILE_TOO_LARGE",
            detail={"max_size_bytes": _MAX_AUDIO_BYTES, "received_size_bytes": len(content)},
        )
    try:
        text = call_whisper_asr(
            content,
            audio.filename or "audio.wav",
            audio.content_type or "audio/wav",
        )
    except ConnectionError as exc:
        raise AppError(str(exc), status_code=503, error_code="STT_UNAVAILABLE")
    except RuntimeError as exc:
        raise AppError(str(exc), status_code=502, error_code="TRANSCRIPTION_FAILED")

    return TranscriptionResponse(text=text)


@router.delete("/{submission_id}", dependencies=[Depends(verify_api_key)])
def delete_submission_endpoint(submission_id: int, db: Session = Depends(get_db)):
    sub = get_form_submission(db, submission_id)
    if not sub:
        raise AppError("Submission not found", status_code=404, error_code="SUBMISSION_NOT_FOUND")

    if sub.output_pdf_path:
        try:
            resolved_out = paths._resolve_project_file(sub.output_pdf_path)
            if resolved_out.exists() and resolved_out.is_file():
                resolved_out.unlink()
        except Exception:
            pass

    delete_form_submission(db, sub)
    return {"status": "success", "message": "Submission and associated output file deleted"}


@router.post("/purge", dependencies=[Depends(verify_api_key)], response_model=PurgeResponse)
def purge_submissions_endpoint(
    days: int | None = Query(default=None, ge=1, le=3650, description="Retention window in days (must be >= 1)"),
    profile_id: UUID | None = Query(default=None, description="Optional profile ID to scope purge"),
    db: Session = Depends(get_db),
):
    retention_days = days if days is not None else RETENTION_PERIOD_DAYS
    purged_count = FormService().purge_submissions(
        db, retention_days=retention_days, profile_id=profile_id
    )
    return PurgeResponse(
        status="success",
        purged_count=purged_count,
        retention_days_used=retention_days,
        profile_id=profile_id,
    )


@router.get("/submissions", response_model=list[FormSubmissionResponse])
def get_submissions(
    profile_id: UUID | None = Query(default=None, description="Optional profile ID to filter submissions"),
    db: Session = Depends(get_db),
):
    return FormService().list_submissions(db, profile_id=profile_id)


@router.get("/submissions/analytics")
def get_submissions_analytics(
    profile_id: UUID | None = Query(default=None, description="Optional profile ID to filter analytics"),
    db: Session = Depends(get_db),
):
    return FormService().get_analytics(db, profile_id=profile_id)


@router.post("/submissions/purge", response_model=PurgeResponse)
def purge_user_submissions_endpoint(
    days: int | None = Query(
        default=None,
        ge=1,
        le=3650,
        description="Optional retention window in days (must be >= 1). If omitted, purges all submissions for current user",
    ),
    current_profile: Profile | None = Depends(get_current_profile),
    db: Session = Depends(get_db),
):
    if current_profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    purged_count = FormService().purge_submissions(
        db, retention_days=days, profile_id=current_profile.profile_id
    )
    return PurgeResponse(
        status="success",
        purged_count=purged_count,
        retention_days_used=days,
        profile_id=current_profile.profile_id,
    )


@router.delete("/submissions/{submission_id}")
def delete_user_submission_endpoint(
    submission_id: int,
    current_profile: Profile | None = Depends(get_current_profile),
    db: Session = Depends(get_db),
):
    if current_profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    deleted = FormService().delete_user_submission(
        db, submission_id, current_profile.profile_id
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Submission not found")
    return {"status": "success", "message": f"Submission {submission_id} deleted successfully"}
