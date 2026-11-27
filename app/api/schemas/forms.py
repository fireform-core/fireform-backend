from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

from app.api.schemas.enums import JobStatus, JobType, LLMProvider


class FormFill(BaseModel):
    template_id: int
    input_text: str | None = None
    input_id: UUID | None = None
    provider: LLMProvider | None = None
    model: str | None = None


class FormFillResponse(BaseModel):
    id: int
    template_id: int
    input_text: str
    output_pdf_path: str
    values: dict | None = None

    model_config = ConfigDict(from_attributes=True)


class TranscriptionResponse(BaseModel):
    text: str


class ModelsResponse(BaseModel):
    models: list[str]
    default: str


class AsyncFormFill(BaseModel):
    template_ids: list[int]
    input_id: UUID
    provider: LLMProvider | None = None
    model: str | None = None

    @field_validator("template_ids")
    def validate_template_ids(cls, value):
        if not value:
            raise ValueError("template_ids cannot be empty")
        return value


class JobResponse(BaseModel):
    job_id: str
    job_type: JobType
    status: JobStatus
    progress_percent: int = 0
    result_url: str | None = None
    error: dict | None = None
    created_at: str | None = None
    updated_at: str | None = None

    class Config:
        from_attributes = True


class AsyncJobSubmitResponse(BaseModel):
    job_id: str
    status: JobStatus
    poll_url: str

    class Config:
        from_attributes = True


class AsyncFormFillResponse(BaseModel):
    jobs: list[AsyncJobSubmitResponse]
    # Present only on a partial failure (HTTP 207): lists the job IDs that were
    # successfully queued before the broker became unreachable.
    error: str | None = None


class TemplateCount(BaseModel):
    template_name: str
    count: int
    percentage: float = 0.0


class DailyCount(BaseModel):
    date: str
    count: int


class TermCount(BaseModel):
    word: str
    count: int


class PeakUsageDay(BaseModel):
    date: str
    count: int


class MostUsedTemplate(BaseModel):
    template_name: str
    count: int
    percentage: float = 0.0


class AnalyticsSummary(BaseModel):
    total_submissions: int
    average_submissions_per_day: float
    active_day_count: int
    peak_usage_day: PeakUsageDay | None = None
    most_used_template: MostUsedTemplate | None = None


class AnalyticsCharts(BaseModel):
    template_distribution: list[TemplateCount]
    daily_activity_trend: list[DailyCount]
    common_terms: list[TermCount]


class SubmissionAnalyticsResponse(BaseModel):
    total_submissions: int
    average_submissions_per_day: float
    active_day_count: int
    peak_usage_day: PeakUsageDay | None = None
    most_used_template: MostUsedTemplate | None = None
    by_template: list[TemplateCount]
    by_date: list[DailyCount]
    common_terms: list[TermCount]
    summary: AnalyticsSummary
    charts: AnalyticsCharts