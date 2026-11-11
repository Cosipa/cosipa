# Profile templates

SVG and HTML live here; `src/scripts/` prepares their values and layout.
The GitHub contribution query lives in `src/queries/profile.graphql`, and badge
font measurements live in `src/data/badge-font.json`.

Templates use Python's standard-library `string.Template` syntax: `$name` or
`${name}`. Use `$$` for a literal dollar sign in a template.

`profile_templates.render()` escapes values for XML/HTML, including attributes.
Its `fragments` argument is only for trusted markup produced by other renderers
(including already-escaped Markdown), never raw fetched text. Substitution is
strict: missing values raise an error.

The SVG files include reusable fragments as well as complete documents. Edit
these templates, not the content-hashed output in `src/assets/generated/`.

Check changes from the repository root:

```sh
python -m unittest discover -s src/scripts/tests -v
python src/scripts/update_profile.py --check
```

To regenerate cards from cached data without network requests:

```sh
python src/scripts/update_profile.py --offline
```
