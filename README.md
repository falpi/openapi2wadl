<p align="center"><img src="https://github.com/user-attachments/assets/fa1be5d4-8d00-4607-b3fa-2c06251baf62" /></p>

# `openapi2wadl.py` : OpenAPI to XSD+WADL+WSDL
<div id="user-content-toc" align="center"><ul><summary><p align="center">Python script to converts JSON OpenAPI 3.0 (or Swagger 2.0) specifications into WADL, WSDL and XSD files.<br/>Supports a wide set of constructs and preserves detailed data types in the generated XSD schema.</p></summary></ul></div>

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
- Generates a comprehensive XML Schema (XSD).
- Nested arrays and objects are fully managed.
- Nested `$ref` schema chains are fully resolved.
- Directly maps `required` property to `minOccurs="0"` XSD attribute when necessary.
- Support the following restriction tokens :
  - `minLength`, `maxLength`, `pattern`, `minimum`, `maximum`, `exclusiveMinimum`, `exclusiveMaximum`.
- Supports nullability in two different ways:
  - Directly maps `nullable` property to the `nillable` XSD attribute.
  - Replace not-nullable atomic types with reusable union `simpleType` that allow empty string as a surrogate for the null value (for those frameworks that do not support the `nillable` attribute).
- Consolidates recurring string length restrictions into reusable `simpleType`'s named and ordered according to length range (e.g. `string64`, `string10to20`, `string32Nillable`) to improve readability and simplify detection of inappropriate or incomplete type definitions.
- Improve human readability:
  - Custom pretty print.
  - Only types referenced in WADL are declared as global elements.
  - Aligns and indents `type` attributes for readability (padding applied).
  - Organizes schema in separated block `Special Types`, `Simple Types`, `Complex Types`, `Elements`.

## Supported Types & Formats
The following Open API Types & Format modifiers are currently supported:

Type          | Format         | Mapped XSD Type | Notes
------------- | -------------- | --------------- | ---------------------------- 
boolean       | - | xs:boolean | true / false
integer       | - | xs:integer | Generic integer number
integer       | int32 | xs:int | 32 bit (-2³¹ to 2³¹-1)
integer       | int64 | xs:long | 64 bit (-2⁶³ to 2⁶³-1)
number        | - | xs:decimal | Arbitrary precision decimal
number        | float | xs:float | 32 bit floating point
number        | double | xs:double | 64 bit floating point
string        | - | xs:string | Generic text
string        | byte | xs:base64Binary | Binary encoded string
string        | date | xs:date | Short date (YYYY-MM-DD)
string        | date-time | xs:dateTime | Date & Time format ISO 8601

---

## 🚫 Limitations

- Unsupported numeric constraint: `multipleOf`
- Composition constructs (`allOf`, `anyOf`, `oneOf`) are not yet supported
- Schema `description` / `title` annotations are not included in WADL/XSD

---

## 🛠️ Usage

```bash
python openapi2wadl.py <input_file.json> [--output-dir <output_directory>]
```

- The output directory is **optional**; if not provided, files are saved in the current directory
- Output files are named after the input JSON file:
  - `<input_file>.wadl`
  - `<input_file>.xsd`

---

## 📌 Recommendations

- Use `$ref` for reusable components (under `definitions` or `components.schemas`)
- Provide clear `produces` and `consumes` values or `content` entries for media type mapping
- Avoid unsupported constraints like `multipleOf`
