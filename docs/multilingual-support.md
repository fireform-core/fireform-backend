# Multilingual Support (English & Spanish)

FireForm supports multiple languages across the user interface and the underlying AI form-filling pipeline (Issue #744). This document details model capabilities, prompt localization architecture, and developer guidelines.

---

## 1. Local Ollama Model Audit

As part of the multilingual workflow evaluation, the local Ollama models configured in FireForm (`OLLAMA_INSTALLABLE_MODELS`) were audited for multilingual instruction-following and JSON extraction capabilities:

| Model Family | Target Languages Tested | Architecture & Pre-training | Native Support Verdict |
| :--- | :--- | :--- | :--- |
| **Qwen 2.5** (`1.5b`, `3b`, `7b`) | English (`en`), Spanish (`es`) | Pretrained on 18T tokens across 29+ languages including English and Spanish. Specialized in structured JSON generation and strict schema constraints. | **Natively Supported** — Follows Spanish system prompts and outputs valid schema JSON without language bleeding. |
| **Llama 3.2** (`3b`) | English (`en`), Spanish (`es`) | Pretrained and instruction-tuned by Meta on 8 core languages (English, German, French, Italian, Portuguese, Hindi, Spanish, Thai). | **Natively Supported** — Accurately handles Spanish incident narratives and maps extracted values into JSON fields. |

### Conclusion
Both available local model families (`qwen2.5` and `llama3.2`) natively support bilingual English/Spanish extraction. No secondary translation proxy or fine-tuning is required.

---

## 2. Architecture Overview

Multilingual operation spans two integrated dimensions:

```
┌─────────────────────────────────────────────────────────────┐
│                       FireForm Frontend                     │
│  - UI Language Switcher in Settings (English / Español)     │
│  - Type-safe i18n localization dictionary                   │
│  - Sends `language: "en" | "es"` in fill requests           │
└──────────────────────────────┬──────────────────────────────┘
                               │ HTTP POST /api/v1/forms/fill
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                    FireForm Backend (FastAPI)               │
│  - FormFill / AsyncFormFill schema accepts `language`       │
│  - Selects localized prompt (prompt.txt / prompt_es.txt)     │
│  - Adapts User Profile context to target language           │
│  - Serializes Weather & Region context in target language   │
│  - Preserves exact PDF widget schema keys & types           │
└──────────────────────────────┬──────────────────────────────┘
                               │ Structured JSON Prompt
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                    Local LLM (Ollama)                       │
│  - Extracts values from narrative in target language        │
│  - Emits JSON strictly matching target schema properties    │
└─────────────────────────────────────────────────────────────┘
```

### 2.1 Prompt Engineering Strategy
- **Schema Key Preservation**: Form field names and schema keys are invariant. Even when filling forms in Spanish, the JSON keys match the PDF widget field names exactly.
- **Value Extraction**: Narrative summaries, incident descriptions, and textual values are extracted in the target language (`es` or `en`).
- **Boolean / Checkbox Consistency**: Checkbox rules remain strictly mapped (`Yes` / `Off`) to maintain compatibility with `pypdf` widget appearance states.

### 2.2 Context Adaptation
- **User Profile Context**: When user profiles are included, section headers and field labels (`Name`, `Role`, `Description`) adapt to the selected language (`Nombre`, `Rol`, `Descripción`).
- **Weather Intelligence**: Hourly weather metrics (temperature, relative humidity, precipitation, wind speed) format with localized units and Spanish/English metric names.
- **Geocoding / ZIP Code**: Nominatim address lookup parses queries in either language, extracting postal codes and place names.

---

## 3. API Usage

### Synchronous Form Fill (`POST /api/v1/forms/fill`)
```json
{
  "template_id": 1,
  "input_text": "El motor 4 respondió a un incendio estructural en Calle Mayor. Fuego contenido en cocina.",
  "language": "es"
}
```

### Asynchronous Form Fill (`POST /api/v1/forms/jobs`)
```json
{
  "template_ids": [1, 2],
  "input_id": "550e8400-e29b-41d4-a716-446655440001",
  "language": "es"
}
```

---

## 4. Adding New Languages

To introduce a new language (e.g., French `fr`):
1. Add the language code to `SupportedLanguage` in `app/api/schemas/enums.py`.
2. Add a localized prompt file under `app/services/form_filler/prompts/prompt_<lang>.txt`.
3. Add locale dictionary in `fireform-frontend/src/renderer/lib/i18n/locales/<lang>.ts`.
4. Update `contracts/schemas/enums.yaml`.
