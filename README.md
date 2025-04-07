# swagger2wadl

Swagger 2.0 to WADL + XSD Converter

This Python script converts a Swagger 2.0 (OpenAPI) JSON file into a WADL file and a corresponding XSD schema file. The output includes proper namespace handling, support for both `application/xml` and `application/json`, and is formatted with pretty-printed XML.

## Features

- Parses Swagger 2.0 JSON files
- Generates an XSD schema from Swagger model definitions
- Produces a WADL file referencing the generated XSD
- Adds XML namespace and prefix declarations correctly (`tns`)
- Includes both XML and JSON representations in responses
- Pretty-printed XML for readability
- CLI-friendly

## Requirements

- Python 3.6+

No additional external libraries are required—this script uses only the Python standard library.

## Usage

```bash
python swagger2wadl.py path/to/swagger.json
```

Optional output directory:

```bash
python swagger2wadl.py path/to/swagger.json --output-dir path/to/output
```

The script will generate two files in the specified (or current) folder:

- `swagger.xsd`: XSD schema with complex types and global elements
- `swagger.wadl`: WADL file referencing the XSD and modeling paths, methods, and responses

## Output Conventions

- Each Swagger definition creates:
  - A global XSD element (referenced in the WADL)
  - A complexType with properties based on `required` fields and data types
- WADL `representation` elements reference the corresponding global element using the `tns` prefix
- Namespace handling is consistent and aligned across both files

## Limitations

- Only Swagger 2.0 JSON format is currently supported
- Nested and recursive definitions are not deeply resolved
- Limited to basic Swagger types (string, integer, boolean, number)
