import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlmodel import Session

from app.api.schemas.enums import LLMProvider
from app.core import paths
from app.core.config import DATA_DIR, FIREFORM_DESKTOP
from app.core.errors.base import AppError
from app.db.repositories import (
    create_form,
    delete_form_submission,
    get_submissions,
    get_submissions_before,
    get_submissions_with_template,
)
from app.models import FormSubmission, Template
from app.services import llm
from app.services.form_filler import filler
from app.services.input import InputService

_STOPWORDS = {
    "the", "and", "a", "of", "to", "in", "is", "that", "it", "was", "for", "on",
    "as", "with", "by", "at", "an", "be", "this", "are", "from", "or", "have",
    "has", "had", "but", "not", "he", "she", "they", "we", "i", "you", "my", "his",
    "her", "their", "our", "me", "him", "them", "us", "about", "there", "their",
    "were", "been", "would", "could", "should", "will", "can", "no", "yes", "any",
    "so", "very", "patient", "presents", "with", "reported", "history", "shows",
    "left", "right", "pain", "due", "after", "before", "emergency", "department",
    "medical", "clinical"
}


class FormService:
    def __init__(self):
        self.input_service = InputService()

    def fill_form(
        self,
        session: Session,
        template: Template,
        input_id: UUID | None = None,
        input_text: str | None = None,
        provider: LLMProvider | None = None,
        model: str | None = None,
    ) -> FormSubmission:
        # Before anything is stored, so a bad pick leaves no stray input behind
        registry = llm.effective_registry(session)
        choice = registry.resolve(provider, model)
        if input_id is not None and not input_text:
            transcript = self.input_service.resolve_transcript(session, input_id)
        elif input_text:
            transcript = input_text
            if input_id is None:
                from app.api.schemas.enums import InputStatus, InputType
                from app.models import Input
                input_record = Input(
                    input_type=InputType.text,
                    status=InputStatus.ready,
                    transcript=input_text,
                    character_count=len(input_text),
                    word_count=len(input_text.split()),
                )
                session.add(input_record)
                session.commit()
                session.refresh(input_record)
                input_id = input_record.input_id
        else:
            raise AppError("Either input_id or input_text is required", status_code=422, error_code="VALIDATION_ERROR")
        return self.fill_and_persist(
            session, template, transcript, input_id, choice.model, choice.provider, registry=registry
        )

    def fill_and_persist(
        self,
        session: Session,
        template: Template,
        transcript: str,
        input_id: UUID,
        model: str | None = None,
        provider: LLMProvider | None = None,
        registry=None,
    ) -> FormSubmission:
        registry = registry or llm.effective_registry(session)
        resolved_pdf = paths._resolve_project_file(template.pdf_path)
        if not resolved_pdf.is_file():
            # The template row is there but its PDF was moved or deleted on disk
            raise AppError(
                f"PDF for template {template.id} not found at {template.pdf_path}",
                status_code=404,
                error_code="TEMPLATE_PDF_NOT_FOUND",
                detail={"template_id": template.id, "pdf_path": template.pdf_path},
            )

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        out_name = f"{resolved_pdf.stem}_{timestamp}_filled.pdf"
        if FIREFORM_DESKTOP:
            # In desktop mode PROJECT_ROOT is the PyInstaller temp dir; write
            # filled PDFs to the persistent DATA_DIR so they survive restarts.
            out_dir = DATA_DIR / "outputs"
            out_dir.mkdir(parents=True, exist_ok=True)
            out_target = out_dir / out_name
        else:
            out_target = resolved_pdf.parent / out_name

        filler.fill(
            pdf_path=str(resolved_pdf),
            narrative=transcript,
            out_path=str(out_target),
            provider=provider,
            model=model,
            description=template.description,
            registry=registry,
        )

        relative_out = paths.make_storable_path(out_target)

        submission = FormSubmission(
            template_id=template.id,
            input_id=input_id,
            input_text=transcript,
            output_pdf_path=relative_out,
        )
        return create_form(session, submission)


    def list_submissions(self, session: Session) -> list[dict]:
        results = get_submissions(session)
        return [
            {
                "id": sub.id,
                "template_id": sub.template_id,
                "template_name": name or "Unknown Template",
                "input_text": sub.input_text,
                "output_pdf_path": sub.output_pdf_path,
                "created_at": sub.created_at.isoformat() if sub.created_at else None,
            }
            for sub, name in results
        ]

    def get_analytics(self, session: Session) -> dict:
        results = get_submissions_with_template(session)

        total_submissions = len(results)

        template_counts = Counter()
        daily_counts = Counter()

        for sub, name in results:
            template_name = name or "Unknown Template"
            template_counts[template_name] += 1

            if sub.created_at:
                date_str = sub.created_at.strftime("%Y-%m-%d")
                daily_counts[date_str] += 1

        all_narratives = " ".join(sub.input_text.lower() for sub, _ in results if sub.input_text)
        found_words = re.findall(r"\b[a-zA-Z]{3,15}\b", all_narratives)
        filtered_words = [w for w in found_words if w not in _STOPWORDS]
        common_terms = [{"word": k, "count": v} for k, v in Counter(filtered_words).most_common(12)]

        sorted_daily = [{"date": k, "count": v} for k, v in sorted(daily_counts.items())]
        sorted_templates = [
            {
                "template_name": k,
                "count": v,
                "percentage": round((v / total_submissions) * 100, 1) if total_submissions > 0 else 0.0,
            }
            for k, v in template_counts.most_common()
        ]

        active_day_count = len(daily_counts)
        average_submissions_per_day = (
            round(total_submissions / active_day_count, 2) if active_day_count > 0 else 0.0
        )

        peak_usage_day = None
        if daily_counts:
            peak_date, peak_count = max(daily_counts.items(), key=lambda item: (item[1], item[0]))
            peak_usage_day = {"date": peak_date, "count": peak_count}

        most_used_template = None
        if sorted_templates:
            top_template = sorted_templates[0]
            most_used_template = {
                "template_name": top_template["template_name"],
                "count": top_template["count"],
                "percentage": top_template["percentage"],
            }

        summary = {
            "total_submissions": total_submissions,
            "average_submissions_per_day": average_submissions_per_day,
            "active_day_count": active_day_count,
            "peak_usage_day": peak_usage_day,
            "most_used_template": most_used_template,
        }

        charts = {
            "template_distribution": sorted_templates,
            "daily_activity_trend": sorted_daily,
            "common_terms": common_terms,
        }

        return {
            "total_submissions": total_submissions,
            "average_submissions_per_day": average_submissions_per_day,
            "active_day_count": active_day_count,
            "peak_usage_day": peak_usage_day,
            "most_used_template": most_used_template,
            "by_template": sorted_templates,
            "by_date": sorted_daily,
            "common_terms": common_terms,
            "summary": summary,
            "charts": charts,
        }

    def purge_submissions(self, session: Session, retention_days: int) -> int:
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=retention_days)
        submissions = get_submissions_before(session, cutoff_date)

        purged_count = 0
        for sub in submissions:
            if sub.output_pdf_path:
                try:
                    resolved_out = paths._resolve_project_file(sub.output_pdf_path)
                    if resolved_out.exists() and resolved_out.is_file():
                        resolved_out.unlink()
                except Exception:
                    pass
            delete_form_submission(session, sub)
            purged_count += 1

        return purged_count
