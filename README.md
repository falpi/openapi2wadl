# swagger2wadl

Swagger 2.0 to WADL + XSD Converter

This tool converts a **Swagger 2.0 (OpenAPI)** JSON specification into:

- a **WADL** (Web Application Description Language) file
- an associated **XSD** (XML Schema Definition)

It is designed to support accurate and schema-compliant transformations suitable for XML-based integrations and legacy systems.

---

## 🚀 Features

### ✅ WADL Generation
- Generates `<application>` WADL document referencing grammar (XSD)
- Supports all HTTP methods (`GET`, `POST`, etc.)
- Maps:
  - **path parameters** → `style="template"`
  - **query parameters** → `style="query"`
  - **headers** → `style="header"`
- Supports **request body** with `$ref` and content types (`consumes`)
- Supports **multiple responses per method**, including:
  - Different `status` codes
  - Each with multiple media types (`produces`)
- Response element references included as `<representation element="tns:Type">`

### ✅ XSD Schema Generation
- Generates an XSD file from `definitions` in Swagger
- Converts Swagger types and formats to correct XSD types
- Supports:
  - `string`, `integer`, `boolean`, `number`
  - `date`, `date-time` (both native types and via `format`)
- Correctly maps `array` with item type (including nested `$ref`)
- Inline object types supported inside properties
- Generates `xs:restriction` with:
  - `minLength`, `maxLength`, `pattern` for `string`
  - `minimum`, `maximum`, `exclusiveMinimum`, `exclusiveMaximum` for `number` and `integer`
- Generates only `<xs:element>` declarations that are referenced in WADL (requests/responses)
- Unused complex types are commented with `<!-- unused type: TypeName -->`
- Pretty-printed XML output

---

## ⚠ Limitations

- ❌ `multipleOf` restriction is **not supported** and will raise an error
- ❌ Swagger 2.0 composition keywords (`allOf`, `anyOf`, `oneOf`) are **not supported**
- ⚠ Recursive `$ref` structures are not resolved (to avoid infinite loops)
- ⚠ Documentation fields like `description` are not (yet) included in XSD annotations
- Only Swagger 2.0 JSON format is supported (not YAML or OpenAPI 3.x)

---

## 💡 Usage

```bash
python swagger2wadl.py my-api-swagger.json --output-dir output/
```

If `--output-dir` is not specified, files will be saved to the current directory.

This will generate:

- `my-api-swagger.wadl`
- `my-api-swagger.xsd`

---

## 📂 File Naming

- The generated WADL and XSD files are named based on the original Swagger file name.
- The `<include href="...">` in WADL uses the base filename only (no path).

---

## 🔧 Error Handling

- Clean error messages for unsupported features (e.g., `multipleOf`)
- Only the error text is printed (no Python traceback) for clarity
