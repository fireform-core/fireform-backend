"""Tests for DELETE /api/v1/templates/{id}, DELETE /api/v1/forms/{id},
POST /api/v1/forms/purge, and API-key access control.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import API_PREFIX
from app.models import FormSubmission, Template
from app.models.models import Profile

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_template(client, name="T1", pdf_path="src/inputs/t.pdf"):
    resp = client.post(f"{API_PREFIX}/templates/create", json={
        "name": name,
        "description": "Test deletion template",
        "pdf_path": pdf_path,
        "fields": {"name": "string"},
    })
    assert resp.status_code == 200, resp.json()
    return resp.json()["id"]


def _seed_submission(db, template_id, output_pdf_path="src/outputs/out.pdf", profile_id=None):
    sub = FormSubmission(
        template_id=template_id,
        profile_id=profile_id,
        input_text="John Doe, firefighter",
        output_pdf_path=output_pdf_path,
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub.id


def _seed_profile(db, name="User A", updated_at=None):
    profile = Profile(
        name=name,
        profession="Firefighter",
        role="Captain",
        updated_at=updated_at or datetime.now(timezone.utc),
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


# ===========================================================================
# DELETE /api/v1/templates/{template_id}
# ===========================================================================

class TestDeleteTemplate:

    def test_delete_template_no_key_required_when_unconfigured(self, client):
        """No API key needed when FIREFORM_API_KEY is empty (default)."""
        tpl_id = _seed_template(client)
        resp = client.delete(f"{API_PREFIX}/templates/{tpl_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "success"

    def test_delete_template_removes_from_db(self, client, db):
        tpl_id = _seed_template(client)
        client.delete(f"{API_PREFIX}/templates/{tpl_id}")
        assert db.get(Template, tpl_id) is None

    def test_delete_template_not_found(self, client):
        resp = client.delete(f"{API_PREFIX}/templates/99999")
        assert resp.status_code == 404

    def test_delete_template_cascades_submissions(self, client, db):
        tpl_id = _seed_template(client)
        sub_id = _seed_submission(db, tpl_id)

        client.delete(f"{API_PREFIX}/templates/{tpl_id}")

        assert db.get(FormSubmission, sub_id) is None
        assert db.get(Template, tpl_id) is None

    def test_delete_template_deletes_pdf_file(self, client, tmp_path, monkeypatch):
        """Verify the template PDF file is removed from disk on delete."""
        monkeypatch.setattr("app.core.paths.PROJECT_ROOT", tmp_path)
        pdf_file = tmp_path / "myform.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake")

        relative_path = "myform.pdf"
        tpl_id = _seed_template(client, pdf_path=relative_path)

        client.delete(f"{API_PREFIX}/templates/{tpl_id}")
        assert not pdf_file.exists()

    def test_delete_template_keeps_pdf_shared_with_another_template(self, client, db, tmp_path, monkeypatch):
        """A PDF still referenced by another template is not removed."""
        monkeypatch.setattr("app.core.paths.PROJECT_ROOT", tmp_path)
        pdf_file = tmp_path / "shared.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake")

        first_id = _seed_template(client, name="First", pdf_path="shared.pdf")
        second_id = _seed_template(client, name="Second", pdf_path="shared.pdf")

        client.delete(f"{API_PREFIX}/templates/{first_id}")
        assert pdf_file.exists()
        assert db.get(Template, second_id) is not None

        # Once the last template using it is gone, the PDF is removed too
        client.delete(f"{API_PREFIX}/templates/{second_id}")
        assert not pdf_file.exists()

    def test_delete_template_keeps_seed_pdf(self, client, tmp_path, monkeypatch):
        """The bundled seed PDF is never removed, even with no other template using it."""
        from app.core.config import SEED_TEMPLATE_PDF_PATH

        monkeypatch.setattr("app.core.paths.PROJECT_ROOT", tmp_path)
        seed_pdf = tmp_path / SEED_TEMPLATE_PDF_PATH
        seed_pdf.parent.mkdir(parents=True)
        seed_pdf.write_bytes(b"%PDF-1.4 seed")

        tpl_id = _seed_template(client, pdf_path=SEED_TEMPLATE_PDF_PATH)

        client.delete(f"{API_PREFIX}/templates/{tpl_id}")
        assert seed_pdf.exists()

    def test_delete_template_deletes_submission_output_pdfs(self, client, db, tmp_path, monkeypatch):
        """Output PDFs of related submissions should be wiped on template deletion."""
        monkeypatch.setattr("app.core.paths.PROJECT_ROOT", tmp_path)

        out_pdf = tmp_path / "filled.pdf"
        out_pdf.write_bytes(b"%PDF-1.4 filled")

        tpl_id = _seed_template(client, pdf_path="tpl.pdf")
        _seed_submission(db, tpl_id, output_pdf_path="filled.pdf")

        client.delete(f"{API_PREFIX}/templates/{tpl_id}")
        assert not out_pdf.exists()


# ===========================================================================
# DELETE /api/v1/forms/{submission_id}
# ===========================================================================

class TestDeleteSubmission:

    def test_delete_submission_no_key_when_unconfigured(self, client, db):
        tpl_id = _seed_template(client)
        sub_id = _seed_submission(db, tpl_id)
        resp = client.delete(f"{API_PREFIX}/forms/{sub_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"

    def test_delete_submission_removes_from_db(self, client, db):
        tpl_id = _seed_template(client)
        sub_id = _seed_submission(db, tpl_id)
        client.delete(f"{API_PREFIX}/forms/{sub_id}")
        assert db.get(FormSubmission, sub_id) is None

    def test_delete_submission_not_found(self, client):
        resp = client.delete(f"{API_PREFIX}/forms/99999")
        assert resp.status_code == 404

    def test_delete_submission_removes_output_pdf(self, client, db, tmp_path, monkeypatch):
        monkeypatch.setattr("app.core.paths.PROJECT_ROOT", tmp_path)
        out_pdf = tmp_path / "filled_out.pdf"
        out_pdf.write_bytes(b"%PDF-1.4")

        tpl_id = _seed_template(client)
        sub_id = _seed_submission(db, tpl_id, output_pdf_path="filled_out.pdf")

        client.delete(f"{API_PREFIX}/forms/{sub_id}")
        assert not out_pdf.exists()


# ===========================================================================
# POST /api/v1/forms/purge
# ===========================================================================

class TestPurgeSubmissions:

    def _seed_old_submission(self, db, tpl_id, days_old=40):
        old_ts = datetime.now(timezone.utc) - timedelta(days=days_old)
        sub = FormSubmission(
            template_id=tpl_id,
            input_text="old data",
            output_pdf_path="src/outputs/old.pdf",
            created_at=old_ts,
        )
        db.add(sub)
        db.commit()
        db.refresh(sub)
        return sub.id

    def test_purge_removes_old_submissions(self, client, db):
        tpl_id = _seed_template(client)
        old_id = self._seed_old_submission(db, tpl_id, days_old=40)
        new_id = _seed_submission(db, tpl_id)  # recent

        resp = client.post(f"{API_PREFIX}/forms/purge?days=30")
        assert resp.status_code == 200
        assert resp.json()["purged_count"] == 1

        assert db.get(FormSubmission, old_id) is None
        assert db.get(FormSubmission, new_id) is not None

    def test_purge_nothing_to_remove(self, client, db):
        tpl_id = _seed_template(client)
        _seed_submission(db, tpl_id)  # recent
        resp = client.post(f"{API_PREFIX}/forms/purge?days=30")
        assert resp.status_code == 200
        assert resp.json()["purged_count"] == 0

    def test_purge_removes_output_pdf_file(self, client, db, tmp_path, monkeypatch):
        monkeypatch.setattr("app.core.paths.PROJECT_ROOT", tmp_path)
        out_pdf = tmp_path / "old_filled.pdf"
        out_pdf.write_bytes(b"%PDF-1.4")

        tpl_id = _seed_template(client)
        old_ts = datetime.now(timezone.utc) - timedelta(days=50)
        sub = FormSubmission(
            template_id=tpl_id,
            input_text="old",
            output_pdf_path="old_filled.pdf",
            created_at=old_ts,
        )
        db.add(sub)
        db.commit()

        resp = client.post(f"{API_PREFIX}/forms/purge?days=30")
        assert resp.status_code == 200
        assert not out_pdf.exists()

    def test_purge_rejects_negative_or_zero_days(self, client, db):
        """Purge with non-positive days (<= 0) should be rejected with 422 to prevent catastrophic deletion."""
        tpl_id = _seed_template(client)
        sub_id = _seed_submission(db, tpl_id)

        resp_negative = client.post(f"{API_PREFIX}/forms/purge?days=-5")
        assert resp_negative.status_code == 422

        resp_zero = client.post(f"{API_PREFIX}/forms/purge?days=0")
        assert resp_zero.status_code == 422

        # Verify submission was not deleted
        assert db.get(FormSubmission, sub_id) is not None


# ===========================================================================
# API-Key Access Control
# ===========================================================================

class TestApiKeyAccessControl:


    @pytest.fixture(autouse=True)
    def _set_api_key(self, monkeypatch):
        monkeypatch.setattr("app.api.deps.FIREFORM_API_KEY", "secret-test-key")

    def test_delete_template_requires_key_when_set(self, client):
        tpl_id = _seed_template(client)
        resp = client.delete(f"{API_PREFIX}/templates/{tpl_id}")
        assert resp.status_code == 401

    def test_delete_template_with_valid_x_api_key(self, client):
        tpl_id = _seed_template(client)
        resp = client.delete(
            f"{API_PREFIX}/templates/{tpl_id}",
            headers={"X-API-Key": "secret-test-key"},
        )
        assert resp.status_code == 200

    def test_delete_template_with_bearer_token(self, client):
        tpl_id = _seed_template(client)
        resp = client.delete(
            f"{API_PREFIX}/templates/{tpl_id}",
            headers={"Authorization": "Bearer secret-test-key"},
        )
        assert resp.status_code == 200

    def test_delete_template_wrong_key_rejected(self, client):
        tpl_id = _seed_template(client)
        resp = client.delete(
            f"{API_PREFIX}/templates/{tpl_id}",
            headers={"X-API-Key": "wrong-key"},
        )
        assert resp.status_code == 401

    def test_delete_submission_requires_key_when_set(self, client, db):
        tpl_id = _seed_template(client)
        sub_id = _seed_submission(db, tpl_id)
        resp = client.delete(f"{API_PREFIX}/forms/{sub_id}")
        assert resp.status_code == 401

    def test_delete_submission_with_valid_key(self, client, db):
        tpl_id = _seed_template(client)
        sub_id = _seed_submission(db, tpl_id)
        resp = client.delete(
            f"{API_PREFIX}/forms/{sub_id}",
            headers={"X-API-Key": "secret-test-key"},
        )
        assert resp.status_code == 200

    def test_purge_requires_key_when_set(self, client):
        resp = client.post(f"{API_PREFIX}/forms/purge?days=30")
        assert resp.status_code == 401

    def test_purge_with_valid_key(self, client, db):
        resp = client.post(
            f"{API_PREFIX}/forms/purge?days=30",
            headers={"X-API-Key": "secret-test-key"},
        )
        assert resp.status_code == 200


# ===========================================================================
# User-Owned Submissions Purge & Deletion
# ===========================================================================

class TestUserSubmissionPurge:

    def _seed_old_submission(
        self, db, tpl_id, profile_id=None, days_old=40, output_pdf_path="src/outputs/old.pdf"
    ):
        old_ts = datetime.now(timezone.utc) - timedelta(days=days_old)
        sub = FormSubmission(
            template_id=tpl_id,
            profile_id=profile_id,
            input_text="old data",
            output_pdf_path=output_pdf_path,
            created_at=old_ts,
        )
        db.add(sub)
        db.commit()
        db.refresh(sub)
        return sub.id

    def test_user_purge_with_retention_days(self, client, db):
        tpl_id = _seed_template(client)
        profile = _seed_profile(db, name="User A")
        old_id = self._seed_old_submission(db, tpl_id, profile_id=profile.profile_id, days_old=40)
        new_id = _seed_submission(db, tpl_id, profile_id=profile.profile_id)

        resp = client.post(f"{API_PREFIX}/forms/submissions/purge?days=30")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "success"
        assert body["purged_count"] == 1
        assert body["retention_days_used"] == 30
        assert body["profile_id"] == str(profile.profile_id)

        assert db.get(FormSubmission, old_id) is None
        assert db.get(FormSubmission, new_id) is not None

    def test_user_purge_without_retention_days_deletes_all_owned(self, client, db, tmp_path, monkeypatch):
        monkeypatch.setattr("app.core.paths.PROJECT_ROOT", tmp_path)
        pdf_old = tmp_path / "u_old.pdf"
        pdf_new = tmp_path / "u_new.pdf"
        pdf_old.write_bytes(b"%PDF-1.4")
        pdf_new.write_bytes(b"%PDF-1.4")

        tpl_id = _seed_template(client)
        profile = _seed_profile(db, name="User A")
        old_id = self._seed_old_submission(
            db, tpl_id, profile_id=profile.profile_id, days_old=40, output_pdf_path="u_old.pdf"
        )
        new_id = _seed_submission(
            db, tpl_id, output_pdf_path="u_new.pdf", profile_id=profile.profile_id
        )

        resp = client.post(f"{API_PREFIX}/forms/submissions/purge")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "success"
        assert body["purged_count"] == 2
        assert body["retention_days_used"] is None
        assert body["profile_id"] == str(profile.profile_id)

        assert db.get(FormSubmission, old_id) is None
        assert db.get(FormSubmission, new_id) is None
        assert not pdf_old.exists()
        assert not pdf_new.exists()

    def test_user_purge_isolation(self, client, db):
        """Purging current user's submissions must not delete another user's or unowned submissions."""
        tpl_id = _seed_template(client)
        now = datetime.now(timezone.utc)
        profile_b = _seed_profile(db, name="User B", updated_at=now - timedelta(hours=1))
        profile_a = _seed_profile(db, name="User A", updated_at=now)

        sub_a_old = self._seed_old_submission(db, tpl_id, profile_id=profile_a.profile_id, days_old=40)
        sub_a_new = _seed_submission(db, tpl_id, profile_id=profile_a.profile_id)
        sub_b_old = self._seed_old_submission(db, tpl_id, profile_id=profile_b.profile_id, days_old=40)
        sub_unowned = _seed_submission(db, tpl_id, profile_id=None)

        resp = client.post(f"{API_PREFIX}/forms/submissions/purge")
        assert resp.status_code == 200
        body = resp.json()
        assert body["purged_count"] == 2
        assert body["profile_id"] == str(profile_a.profile_id)

        assert db.get(FormSubmission, sub_a_old) is None
        assert db.get(FormSubmission, sub_a_new) is None
        assert db.get(FormSubmission, sub_b_old) is not None
        assert db.get(FormSubmission, sub_unowned) is not None

    def test_user_purge_no_profile_returns_404(self, client):
        resp = client.post(f"{API_PREFIX}/forms/submissions/purge")
        assert resp.status_code == 404

    def test_user_purge_invalid_days_returns_422(self, client, db):
        tpl_id = _seed_template(client)
        profile = _seed_profile(db, name="User A")
        sub_id = _seed_submission(db, tpl_id, profile_id=profile.profile_id)

        assert client.post(f"{API_PREFIX}/forms/submissions/purge?days=0").status_code == 422
        assert client.post(f"{API_PREFIX}/forms/submissions/purge?days=-5").status_code == 422
        assert db.get(FormSubmission, sub_id) is not None

    def test_user_delete_specific_submission(self, client, db, tmp_path, monkeypatch):
        monkeypatch.setattr("app.core.paths.PROJECT_ROOT", tmp_path)
        out_pdf = tmp_path / "user_sub.pdf"
        out_pdf.write_bytes(b"%PDF-1.4")

        tpl_id = _seed_template(client)
        profile = _seed_profile(db, name="User A")
        sub_id = _seed_submission(
            db, tpl_id, output_pdf_path="user_sub.pdf", profile_id=profile.profile_id
        )

        resp = client.delete(f"{API_PREFIX}/forms/submissions/{sub_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"
        assert db.get(FormSubmission, sub_id) is None
        assert not out_pdf.exists()

    def test_user_delete_other_users_submission_returns_403(self, client, db):
        tpl_id = _seed_template(client)
        now = datetime.now(timezone.utc)
        profile_b = _seed_profile(db, name="User B", updated_at=now - timedelta(hours=1))
        _seed_profile(db, name="User A", updated_at=now)
        sub_b = _seed_submission(db, tpl_id, profile_id=profile_b.profile_id)

        resp = client.delete(f"{API_PREFIX}/forms/submissions/{sub_b}")
        assert resp.status_code == 403
        assert db.get(FormSubmission, sub_b) is not None

    def test_user_delete_nonexistent_submission_returns_404(self, client, db):
        _seed_profile(db, name="User A")
        resp = client.delete(f"{API_PREFIX}/forms/submissions/99999")
        assert resp.status_code == 404

    def test_user_delete_no_profile_returns_404(self, client, db):
        tpl_id = _seed_template(client)
        sub_id = _seed_submission(db, tpl_id)
        resp = client.delete(f"{API_PREFIX}/forms/submissions/{sub_id}")
        assert resp.status_code == 404

    def test_admin_purge_scoped_by_profile_id(self, client, db):
        tpl_id = _seed_template(client)
        profile_a = _seed_profile(db, name="User A")
        profile_b = _seed_profile(db, name="User B")
        sub_a_old = self._seed_old_submission(db, tpl_id, profile_id=profile_a.profile_id, days_old=40)
        sub_b_old = self._seed_old_submission(db, tpl_id, profile_id=profile_b.profile_id, days_old=40)

        resp = client.post(
            f"{API_PREFIX}/forms/purge?days=30&profile_id={profile_a.profile_id}"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["purged_count"] == 1
        assert body["profile_id"] == str(profile_a.profile_id)
        assert db.get(FormSubmission, sub_a_old) is None
        assert db.get(FormSubmission, sub_b_old) is not None

    def test_list_and_analytics_filter_by_profile_id(self, client, db):
        tpl_id = _seed_template(client)
        profile_a = _seed_profile(db, name="User A")
        profile_b = _seed_profile(db, name="User B")
        _seed_submission(db, tpl_id, profile_id=profile_a.profile_id)
        _seed_submission(db, tpl_id, profile_id=profile_b.profile_id)

        list_resp = client.get(
            f"{API_PREFIX}/forms/submissions?profile_id={profile_a.profile_id}"
        )
        assert list_resp.status_code == 200
        items = list_resp.json()
        assert len(items) == 1
        assert items[0]["profile_id"] == str(profile_a.profile_id)

        analytics_resp = client.get(
            f"{API_PREFIX}/forms/submissions/analytics?profile_id={profile_a.profile_id}"
        )
        assert analytics_resp.status_code == 200
        assert analytics_resp.json()["total_submissions"] == 1

    def test_fill_form_persists_profile_id(self, client, mock_controller, db, tmp_path, monkeypatch):
        monkeypatch.setattr("app.core.paths.PROJECT_ROOT", tmp_path)
        pdf_file = tmp_path / "employee.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake")
        tpl_id = _seed_template(client, pdf_path=str(pdf_file.relative_to(tmp_path)))
        profile = _seed_profile(db, name="User A")

        resp = client.post(
            f"{API_PREFIX}/forms/fill",
            json={
                "template_id": tpl_id,
                "input_text": "Incident narrative text.",
                "profile_id": str(profile.profile_id),
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["profile_id"] == str(profile.profile_id)
        fetched = db.get(FormSubmission, data["id"])
        assert fetched.profile_id == profile.profile_id
