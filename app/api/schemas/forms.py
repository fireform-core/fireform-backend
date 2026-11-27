from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api.schemas.enums import JobStatus, JobType, LLMProvider


class FormFill(BaseModel):
    template_id: int
    input_text: str | None = None
    input_id: UUID | None = None
    profile_id: UUID | None = Field(default=None, description="Optional profile ID creating this submission")
    provider: LLMProvider | None = None
    model: str | None = None


class FormFillResponse(BaseModel):
    id: int
    template_id: int
    profile_id: UUID | None = Field(default=None, description="Profile ID owning this submission")
    input_text: str
    output_pdf_path: str
    values: dict | None = None

    model_config = ConfigDict(from_attributes=True)


class FormSubmissionResponse(BaseModel):
    id: int
    template_id: int
    template_name: str
    profile_id: UUID | None = Field(default=None, description="Profile ID owning this submission")
    input_text: str | None = None
    output_pdf_path: str
    created_at: str | None = None

    model_config = ConfigDict(from_attributes=True)


class PurgeResponse(BaseModel):
    status: str
    purged_count: int
    retention_days_used: int | None = None
    profile_id: UUID | None = Field(default=None, description="Profile ID if purge was scoped to a user")


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