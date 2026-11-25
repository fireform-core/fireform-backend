"""Narrative + fillable PDF -> filled PDF.

    result = filler.fill("ics_201.pdf", narrative, "ics_201_filled.pdf")

Which LLM answers is picked per call (provider, model), defaulting to
LLM_PROVIDER and LLM_MODEL. See app/services/llm.

fill() builds the schema (template.py), sends prompt.txt + narrative + schema
to the LLM, maps the answer back to widget names and writes the filled PDF.
It returns every intermediate step so callers (the benchmark) can save them.
"""

import json
import os

from pypdf import PdfWriter

from app.models.models import Profile
from app.services import llm

from . import template
from .geometry import CHECKBOX, RADIOBUTTON, SIGNATURE, drop_null_parents, on_state, page_widgets

_PROMPT_DIR = os.path.join(os.path.dirname(__file__), "prompts")


def get_base_prompt(language: str = "en") -> str:
    lang = language.lower() if language else "en"
    prompt_file = os.path.join(_PROMPT_DIR, f"prompt_{lang}.txt")
    if os.path.isfile(prompt_file):
        with open(prompt_file, "r", encoding="utf-8") as f:
            return f.read()
    default_prompt_file = os.path.join(os.path.dirname(__file__), "prompt.txt")
    if os.path.isfile(default_prompt_file):
        with open(default_prompt_file, "r", encoding="utf-8") as f:
            return f.read()
    return ""


PROMPT_EN = get_base_prompt("en")
PROMPT_ES = get_base_prompt("es")
PROMPT = PROMPT_EN


def append_profile_context(base_prompt: str, profile: Profile = None, language: str = "en") -> str:
    if not profile:
        return base_prompt

    desc = profile.description if profile.description else "N/A"
    lang = language.lower() if language else "en"

    if lang == "es":
        profile_context = (
            "=== CONTEXTO DEL PERFIL DE USUARIO ===\n"
            "El formulario está siendo completado por un usuario con el siguiente perfil:\n"
            f"- Nombre: {profile.name}\n"
            f"- Profesión: {profile.profession}\n"
            f"- Rol: {profile.role}\n"
            f"- Descripción: {desc}\n"
        )
        if profile.custom_fields:
            for key, value in profile.custom_fields.items():
                profile_context += f"- {key.capitalize()}: {value}\n"
        profile_context += "\nPor favor usa este contexto para proporcionar sugerencias de campos y validaciones más relevantes y adaptadas.\n\n"
    else:
        profile_context = (
            "=== USER PROFILE CONTEXT ===\n"
            "The form is being filled out by a user with the following profile:\n"
            f"- Name: {profile.name}\n"
            f"- Profession: {profile.profession}\n"
            f"- Role: {profile.role}\n"
            f"- Description: {desc}\n"
        )
        if profile.custom_fields:
            for key, value in profile.custom_fields.items():
                profile_context += f"- {key.capitalize()}: {value}\n"
        profile_context += "\nPlease use this context to provide more relevant and tailored field suggestions and validations.\n\n"

    return profile_context + base_prompt


def fill(
    pdf_path,
    narrative,
    out_path=None,
    model=None,
    description="",
    provider=None,
    registry=None,
    profile: Profile = None,
    language: str = "en",
):
    """Fill pdf_path from the narrative. Writes the PDF when out_path is given.

    Returns {schema, tables, groups, prompt, response_text, values}: the
    schema sent to the LLM, the exact prompt, the raw model output,
    and the flat {widget name: value} dict used to fill the PDF.
    """
    schema, tables, groups = template.create_template(pdf_path)
    strip_empty_descriptions(schema["properties"])

    prompt = build_prompt(narrative, schema, description, profile, language=language)
    response_text = call_model(prompt, schema, model, provider, registry=registry)

    # Tables come back as arrays of rows; map them to widget names
    values = template.expand_output(json.loads(response_text), tables, groups)

    if out_path:
        write_pdf(pdf_path, values, out_path)

    return {
        "schema": schema,
        "tables": tables,
        "groups": groups,
        "prompt": prompt,
        "response_text": response_text,
        "values": values,
    }


def strip_empty_descriptions(props):
    for prop in props.values():
        if prop.get("description") == "":
            del prop["description"]
        if "items" in prop:
            strip_empty_descriptions(prop["items"]["properties"])
    return props


def build_prompt(narrative, schema, description="", profile: Profile = None, language: str = "en"):
    # Omitted entirely when blank so the model is not handed an empty block.
    context = f"<template_description>\n{description}\n</template_description>\n\n" if description else ""
    user_content = (
        context
        + "<incident_narrative>\n"
        + narrative
        + "\n</incident_narrative>\n\n<target_json_schema>\n"
        + json.dumps(schema["properties"], indent=2, ensure_ascii=False)
        + "\n</target_json_schema>"
    )
    base_prompt = get_base_prompt(language).rstrip() + "\n\n" + user_content
    return append_profile_context(base_prompt, profile, language=language)


def call_model(prompt, schema, model=None, provider=None, registry=None):
    """The answer as JSON text shaped by the schema. None falls back to the defaults."""
    active_registry = registry or llm.get_registry()
    return active_registry.generate_json(prompt, schema, provider, model)


def write_pdf(pdf_path, values, out_path):
    new_doc = PdfWriter(clone_from=pdf_path)

    # pypdf sets checkboxes and radio buttons by appearance-state name ("/Yes"), not "Yes"
    for page in new_doc.pages:
        drop_null_parents(page)
        page_values = {}
        for widget in page_widgets(page):
            if widget.field_type == SIGNATURE:
                continue
            value = values.get(widget.field_name, "")
            if widget.field_type == CHECKBOX:
                value = on_state(widget) if value == "Yes" else "/Off"
            elif widget.field_type == RADIOBUTTON:
                # The buttons of a group share its name, so all of them get the
                # chosen option's state and pypdf turns on the one that has it
                value = f"/{value}" if value and value != "Off" else "/Off"
            page_values[widget.field_name] = "" if value is None else str(value)
        if page_values:
            new_doc.update_page_form_field_values(page, page_values)

    new_doc.write(out_path)
