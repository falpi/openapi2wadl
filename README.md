# `openapi2wadl.py` : OpenAPI to WADL+XSD
<div id="user-content-toc" align="center"><ul><summary><p align="center">Python script to converts JSON OpenAPI 3.0 (or Swagger 2.0) specifications into WADL and XSD files.<br/>Supports a wide set of constructs and preserves detailed data types in the generated XSD schema.</p></summary></ul></div>

---

## 🚀 Features

### ✅ WADL Generation
- Supports both Swagger 2.0 and OpenAPI 3.0 (auto-detected)
- Generates WADL `<resources>`, `<resource>`, `<method>`, `<request>`, and `<response>`
- Supports `produces` / `consumes` in Swagger and `content` in OpenAPI
- Includes all declared media types in `<representation>`
- Handles parameters of type `query`, `header`, `path`, and `body`
- Resolves all `$ref` references for requests and responses

### ✅ XSD Schema Generation
- Generates a comprehensive XML Schema (XSD) for definitions used in WADL.
- Only types referenced in WADL are declared as global elements.
- Supports array types with proper `<xs:sequence>` wrapping.
- Inline object types and deeply nested `$ref` are fully resolved.
- Enforces string restrictions:
  - `minLength`, `maxLength`, `pattern`.
- Enforces number restrictions:
  - `minimum`, `maximum`, `exclusiveMinimum`, `exclusiveMaximum`.
- Maps standard integer constraints:
  - `min=0` → `xs:nonNegativeInteger`
  - `min=1` → `xs:positiveInteger`
- Consolidates recurring string restrictions into reusable named `simpleType`'s named according to length range, e.g. `string64Type`, `string32TypeNillable`
- Improve human readabilityy:
  - Custom pretty print.
  - Aligns and indents `type` attributes for readability (padding applied)
  - Organizes schema in three separated block `SimpleTypes`, `ComplexTypes`, `Elements`
 
---

## 🚫 Limitations

- Unsupported numeric constraint: `multipleOf`
- Composition constructs (`allOf`, `anyOf`, `oneOf`) are not yet supported
- Recursive definitions are handled safely (no infinite loops), but without semantic merging
- Schema `description` / `title` annotations are not included in WADL/XSD

---

## 🛠️ Usage

```bash
python openapi2wadl.py <input_file.json> [--output-dir <output_directory>]
```

- The output directory is **optional**; if not provided, files are saved in the current directory
- Output files are named after the input JSON file:
  - `<name>.wadl`
  - `<name>.xsd`

---

## 📌 Recommendations

- Use `$ref` for reusable components (under `definitions` or `components.schemas`)
- Provide clear `produces` and `consumes` values or `content` entries for media type mapping
- Avoid unsupported constraints like `multipleOf`
