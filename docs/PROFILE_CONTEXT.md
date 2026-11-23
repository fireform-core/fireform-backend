# Profile context in form fills

A form fill can add the saved profile to the model input. It is off by default.

Send `include_profile_context: true` to either fill endpoint:

- `POST /api/v1/forms/fill`
- `POST /api/v1/forms/jobs`

```json
{
  "template_id": 1,
  "input_text": "Fire on Ridge Road. Two engines sent.",
  "include_profile_context": true
}
```

- The profile used is the one `GET /api/v1/profiles/` returns.
- If no profile is saved, the fill runs without it.
- For `/forms/jobs` the profile is read when the request is submitted, so all
  jobs in that request use the same values.
- With a cloud provider, the profile's name, profession, role, description and
  custom fields are sent to that provider.
