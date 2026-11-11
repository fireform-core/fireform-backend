"""Tests for app.services.form_filler without a real LLM.

Uses the real ICS 205A from the benchmark data: the template is built from the
PDF itself, the model call is patched, and the filled PDF is read back. None of
the benchmark PDFs has a radio group, so those tests write a small form instead.
"""

import json
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfReader

from app.services.form_filler import filler, geometry, template
from app.services.llm import ModelInfo

ICS_205A = str(Path(__file__).resolve().parents[1] / "benchmark/data/pdfs/ics_205a.pdf")
TABLE = "resource_summary_0_table"
TEMPLATE_DESCRIPTION = "Wildfire incident communications plan"


def test_template_has_geometry_table_and_tooltip_descriptions():
    schema, tables, groups = template.create_template(ICS_205A)
    props = schema["properties"]

    # The 34-row contact list comes back as one array of rows
    assert props[TABLE]["type"] == "array"
    assert list(props[TABLE]["items"]["properties"]) == [
        "Incident_Assigned_Position",
        "Name_Alphabetized",
        "Method_s_of_Contact_phone_pager_cell_etc",
    ]
    assert tables[0]["row_count"] == 34
    assert groups["Name_Alphabetized"][0] == "Name AlphabetizedRow1"

    # Scalar fields keep their PDF names and use the /TU tooltip as description
    assert props["1 Incident Name_9"]["description"] == "Incident Name:"


def test_fill_maps_rows_back_to_widgets_and_writes_pdf(tmp_path):
    answer = {
        "1 Incident Name_9": "Blackwood Canyon Wildfire",
        TABLE: [
            {"Incident_Assigned_Position": "IC", "Name_Alphabetized": "Ana Diaz",
             "Method_s_of_Contact_phone_pager_cell_etc": "555-0101"},
            {"Incident_Assigned_Position": "Safety", "Name_Alphabetized": "Bo Chen",
             "Method_s_of_Contact_phone_pager_cell_etc": "555-0102"},
        ],
    }
    out_path = tmp_path / "filled.pdf"

    with patch.object(filler, "call_model", return_value=json.dumps(answer)) as call:
        result = filler.fill(
            ICS_205A,
            "Narrative text.",
            str(out_path),
            "test-model",
            TEMPLATE_DESCRIPTION,
        )

    prompt, schema, model, provider = call.call_args.args
    assert (
        f"<template_description>\n{TEMPLATE_DESCRIPTION}\n</template_description>" in prompt
    )
    assert "<incident_narrative>\nNarrative text.\n</incident_narrative>" in prompt
    assert prompt.startswith(filler.PROMPT.rstrip())
    assert model == "test-model"
    assert provider is None

    assert result["values"]["Name AlphabetizedRow2"] == "Bo Chen"

    fields = PdfReader(str(out_path)).get_fields()
    assert fields["1 Incident Name_9"]["/V"] == "Blackwood Canyon Wildfire"
    assert fields["Incident Assigned PositionRow1"]["/V"] == "IC"
    assert fields["Methods of Contact phone pager cell etcRow2"]["/V"] == "555-0102"
    assert fields["Name AlphabetizedRow3"].get("/V", "") == ""


def test_fill_without_model_lets_the_llm_pick_its_default():
    with patch.object(filler, "call_model", return_value="{}") as call:
        filler.fill(ICS_205A, "Narrative text.", description=TEMPLATE_DESCRIPTION)

    assert call.call_args.args[2] is None


def test_call_model_goes_through_the_picked_llm(test_llm):
    with (
        patch.object(test_llm, "list_models", return_value=[ModelInfo(name="m")]),
        patch.object(test_llm, "generate_json", return_value="{}") as generate,
    ):
        assert filler.call_model("prompt", {"type": "object"}, "m", "ollama") == "{}"

    generate.assert_called_once_with("prompt", {"type": "object"}, "m")


def test_call_model_without_a_pick_uses_the_default(test_llm):
    with patch.object(test_llm, "generate_json", return_value="{}") as generate:
        filler.call_model("prompt", {"type": "object"})

    generate.assert_called_once_with("prompt", {"type": "object"}, "qwen2.5:1.5b")


def _radio_form(path):
    """A one-page form with a text field and two radio groups. Each button has
    its own 'on' appearance state (/Male, /Female) next to /Off, as Acrobat
    writes them."""
    def button(parent, state, x, y):
        return (
            f"<< /Type /Annot /Subtype /Widget /Parent {parent} 0 R"
            f" /Rect [{x} {y} {x + 12} {y + 12}] /AS /Off"
            f" /AP << /N << /{state} 11 0 R /Off 11 0 R >> >> >>"
        )

    objects = [
        "<< /Type /Catalog /Pages 2 0 R /AcroForm << /Fields [4 0 R 5 0 R 8 0 R]"
        " /DA (/Helv 0 Tf 0 g) /DR << /Font << /Helv << /Type /Font /Subtype /Type1"
        " /BaseFont /Helvetica >> >> >> >> >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200]"
        " /Annots [4 0 R 6 0 R 7 0 R 9 0 R 10 0 R] >>",
        "<< /Type /Annot /Subtype /Widget /FT /Tx /T (Name) /Rect [20 160 200 175] >>",
        "<< /FT /Btn /Ff 49152 /T (Gender) /Kids [6 0 R 7 0 R] >>",
        button(5, "Male", 20, 120),
        button(5, "Female", 80, 120),
        "<< /FT /Btn /Ff 49152 /T (ER) /Kids [9 0 R 10 0 R] >>",
        button(8, "Yes", 20, 80),
        button(8, "No", 80, 80),
        "<< /Length 0 >>\nstream\n\nendstream",
    ]
    pdf = bytearray(b"%PDF-1.7\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf += f"{number} 0 obj\n{body}\nendobj\n".encode()
    xref, size = len(pdf), len(objects) + 1
    pdf += f"xref\n0 {size}\n0000000000 65535 f \n".encode()
    pdf += "".join(f"{offset:010d} 00000 n \n" for offset in offsets).encode()
    pdf += f"trailer\n<< /Size {size} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(bytes(pdf))
    return str(path)


def _radio_states(pdf_path, group):
    """{state that turns each button of the group on: the button's current /AS}"""
    return {
        geometry.on_state(widget): widget.annotation["/AS"]
        for page in PdfReader(pdf_path).pages
        for widget in geometry.page_widgets(page)
        if widget.field_name == group
    }


def test_radio_groups_offer_their_options(tmp_path):
    schema, _, _ = template.create_template(_radio_form(tmp_path / "radio.pdf"))
    props = schema["properties"]

    assert props["Gender"]["enum"] == ["Male", "Female", "Off"]
    assert props["ER"]["enum"] == ["Yes", "No", "Off"]
    assert "type" not in props["Gender"]
    assert props["Name"]["type"] == "string"


def test_fill_turns_on_the_chosen_radio_button(tmp_path):
    pdf_path = _radio_form(tmp_path / "radio.pdf")
    out_path = tmp_path / "filled.pdf"
    answer = {"Name": "Ana Diaz", "Gender": "Female", "ER": "Yes"}

    with patch.object(filler, "call_model", return_value=json.dumps(answer)) as call:
        filler.fill(pdf_path, "Narrative text.", str(out_path))

    assert call.call_args.args[1]["properties"]["Gender"]["enum"] == ["Male", "Female", "Off"]
    assert _radio_states(out_path, "Gender") == {"/Male": "/Off", "/Female": "/Female"}
    # Every button used to get the last button's state, so "Yes" turned on "No"
    assert _radio_states(out_path, "ER") == {"/Yes": "/Yes", "/No": "/Off"}
    assert PdfReader(str(out_path)).get_fields()["Name"]["/V"] == "Ana Diaz"


def test_radio_group_answered_off_stays_unselected(tmp_path):
    pdf_path = _radio_form(tmp_path / "radio.pdf")
    out_path = tmp_path / "filled.pdf"

    filler.write_pdf(pdf_path, {"Gender": "Off", "ER": ""}, str(out_path))

    assert _radio_states(out_path, "Gender") == {"/Male": "/Off", "/Female": "/Off"}
    assert _radio_states(out_path, "ER") == {"/Yes": "/Off", "/No": "/Off"}


def test_expand_output_treats_null_table_as_empty():
    # Providers without structured output (Anthropic) can answer null for a table
    tables = [{"name": TABLE, "columns": ["Name"]}]
    groups = {"Name": ["Name_Row1", "Name_Row2"]}

    values = template.expand_output({TABLE: None, "Incident Name": "Ridge Fire"}, tables, groups)

    assert values == {"Incident Name": "Ridge Fire"}
