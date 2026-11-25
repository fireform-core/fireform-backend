"""Opt-in profile context for sync and async form fills."""

from unittest.mock import patch

import pytest
from sqlmodel import Session

from app.api.schemas.enums import InputStatus, InputType
from app.core.config import API_PREFIX
from app.models import Input, Job, Template
from app.models.models import Profile

PROFILE = {
    "name": "Test User",
    "profession": "Firefighter",
    "role": "Fire Captain",
    "description": None,
    "custom_fields": {"station": "Station 4"},
}


@pytest.fixture
def ids(db, tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.form.paths.PROJECT_ROOT", tmp_path)
    (tmp_path / "t.pdf").touch()
    template = Template(name="T", description="Test template", pdf_path="t.pdf", fields={})
    record = Input(input_type=InputType.text, status=InputStatus.ready, transcript="Fire on Ridge Road")
    db.add_all([template, record])
    db.commit()
    return template.id, str(record.input_id)


@pytest.fixture
def saved_profile(db):
    db.add(Profile(**PROFILE))
    db.commit()


def _sync_fill(client, ids, **body):
    seen = {}

    def fake_fill(**kwargs):
        # Read it during the call like the filler does; the session closes afterwards
        profile = kwargs.get("profile")
        seen["profile"] = (profile.name, profile.role) if profile else None

    with patch("app.services.form.filler.fill", side_effect=fake_fill):
        resp = client.post(f"{API_PREFIX}/forms/fill", json={"template_id": ids[0], "input_id": ids[1], **body})
    assert resp.status_code == 200, resp.json()
    return seen["profile"]


def _async_fill(client, ids, **body):
    with patch("app.api.routes.jobs.fill_form_task") as task:
        resp = client.post(f"{API_PREFIX}/forms/jobs", json={"template_ids": [ids[0]], "input_id": ids[1], **body})
    assert resp.status_code == 200, resp.json()
    args = task.apply_async.call_args.args[0]
    return args[5] if len(args) > 5 else None


def test_sync_fill_uses_profile_when_enabled(client, ids, saved_profile):
    assert _sync_fill(client, ids, include_profile_context=True) == ("Test User", "Fire Captain")


@pytest.mark.parametrize("body", [{}, {"include_profile_context": False}])
def test_sync_fill_omits_profile_unless_enabled(client, ids, saved_profile, body):
    assert _sync_fill(client, ids, **body) is None


def test_sync_fill_works_without_a_saved_profile(client, ids):
    assert _sync_fill(client, ids, include_profile_context=True) is None


def test_async_fill_queues_profile_when_enabled(client, ids, saved_profile):
    assert _async_fill(client, ids, include_profile_context=True) == PROFILE


@pytest.mark.parametrize("body", [{}, {"include_profile_context": False}])
def test_async_fill_omits_profile_unless_enabled(client, ids, saved_profile, body):
    assert _async_fill(client, ids, **body) is None


def test_async_fill_works_without_a_saved_profile(client, ids):
    assert _async_fill(client, ids, include_profile_context=True) is None


def test_task_hands_queued_profile_to_filler(db, ids):
    from app.tasks.fill import fill_form_task

    job = Job(job_type="form_generation", template_id=ids[0], input_text="Fire")
    job.celery_task_id = job.job_id
    db.add(job)
    db.commit()

    fill_form_task.push_request(id=job.celery_task_id)
    try:
        with (
            patch("app.tasks.fill.get_session", lambda: iter([Session(db.get_bind())])),
            patch("app.services.form.filler.fill") as fill,
        ):
            fill_form_task.run(ids[0], "Fire", ids[1], None, None, PROFILE)
    finally:
        fill_form_task.pop_request()

    assert fill.call_args.kwargs["profile"].custom_fields == {"station": "Station 4"}
