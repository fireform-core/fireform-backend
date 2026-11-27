from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.services.form import FormService


def test_get_analytics_empty():
    service = FormService()
    mock_session = MagicMock()

    with patch("app.services.form.get_submissions_with_template", return_value=[]):
        res = service.get_analytics(mock_session)

    assert res["total_submissions"] == 0
    assert res["average_submissions_per_day"] == 0.0
    assert res["active_day_count"] == 0
    assert res["peak_usage_day"] is None
    assert res["most_used_template"] is None
    assert res["by_template"] == []
    assert res["by_date"] == []
    assert res["common_terms"] == []
    assert res["summary"]["total_submissions"] == 0
    assert res["charts"]["template_distribution"] == []
    assert res["charts"]["daily_activity_trend"] == []
    assert res["charts"]["common_terms"] == []


def test_get_analytics_populated():
    service = FormService()
    mock_session = MagicMock()

    sub1 = MagicMock()
    sub1.created_at = datetime(2026, 10, 29, 10, 0, tzinfo=timezone.utc)
    sub1.input_text = "Patient transported to hospital by engine team."

    sub2 = MagicMock()
    sub2.created_at = datetime(2026, 10, 30, 11, 0, tzinfo=timezone.utc)
    sub2.input_text = "Patient arrived safely with engine crew."

    sub3 = MagicMock()
    sub3.created_at = datetime(2026, 10, 30, 14, 0, tzinfo=timezone.utc)
    sub3.input_text = "Structure fire reported at residential building."

    mock_results = [
        (sub1, "Template A"),
        (sub2, "Template A"),
        (sub3, "Template B"),
    ]

    with patch("app.services.form.get_submissions_with_template", return_value=mock_results):
        res = service.get_analytics(mock_session)

    assert res["total_submissions"] == 3
    assert res["active_day_count"] == 2
    assert res["average_submissions_per_day"] == 1.5
    assert res["peak_usage_day"] == {"date": "2026-10-30", "count": 2}
    assert res["most_used_template"] == {
        "template_name": "Template A",
        "count": 2,
        "percentage": 66.7,
    }
    assert len(res["by_template"]) == 2
    assert res["by_template"][0]["template_name"] == "Template A"
    assert res["by_template"][0]["count"] == 2
    assert res["by_template"][0]["percentage"] == 66.7
    assert res["by_template"][1]["template_name"] == "Template B"
    assert res["by_template"][1]["count"] == 1
    assert res["by_template"][1]["percentage"] == 33.3

    assert len(res["by_date"]) == 2
    assert res["by_date"][0] == {"date": "2026-10-29", "count": 1}
    assert res["by_date"][1] == {"date": "2026-10-30", "count": 2}

    term_words = [t["word"] for t in res["common_terms"]]
    assert "engine" in term_words
    assert "transported" in term_words

    # Structure contracts & summary / charts
    assert res["summary"]["total_submissions"] == 3
    assert res["charts"]["template_distribution"] == res["by_template"]
    assert res["charts"]["daily_activity_trend"] == res["by_date"]
    assert res["charts"]["common_terms"] == res["common_terms"]
