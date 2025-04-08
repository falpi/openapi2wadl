# swagger2wadl.py
# Author: ChatGPT (with user's collaboration)
# Purpose: Convert a Swagger 2.0 (JSON format) file into a WADL file and related XSD.
# Features:
# - Extracts Swagger definitions to build the XSD schema
# - Generates a WADL file that references the XSD via namespace and include
# - Supports pretty-printed XML output and command line usage
# - Supports array types, date/date-time formats, string restrictions (minLength, maxLength, pattern), and parameters including headers
# - Includes body parameters in the WADL <request> with appropriate representations

import json
import os
import argparse
import xml.etree.ElementTree as ET
from xml.dom import minidom
from pathlib import Path

# Namespace constants
XSD_NAMESPACE = "http://www.w3.org/2001/XMLSchema"
WADL_NAMESPACE = "http://wadl.dev.java.net/2009/02"
XSD_TARGET_NAMESPACE = "http://example.com/schema"
XSD_PREFIX = "tns"

# Register namespaces for XML output
ET.register_namespace("xs", XSD_NAMESPACE)
ET.register_namespace("", WADL_NAMESPACE)
ET.register_namespace(XSD_PREFIX, XSD_TARGET_NAMESPACE)

def prettify_xml(elem):
    rough_string = ET.tostring(elem, 'utf-8')
    reparsed = minidom.parseString(rough_string)
    return reparsed.toprettyxml(indent="  ")

def parse_swagger(swagger):
    return swagger.get("definitions", {})

def resolve_inline_properties(schema, definitions):
    """
    Espande le proprietà inline di uno schema (senza $ref) ricorsivamente,
    restituendo un dizionario {nome_prop: definizione completa} e required.
    I $ref vengono lasciati intatti per mantenere il legame tra i tipi.
    """
    if "$ref" in schema:
        return {}, []

    properties = schema.get("properties", {})
    required = schema.get("required", [])
    return properties, required

def collect_used_definitions_from_wadl(swagger, definitions):
    """
    Analizza lo Swagger e raccoglie ricorsivamente tutti i nomi delle definizioni referenziate,
    incluse quelle annidate via $ref in oggetti o array.
    """
    used = set()

    def visit_schema(schema):
        if not isinstance(schema, dict):
            return
        # Caso diretto: $ref
        if "$ref" in schema:
            ref_name = schema["$ref"].split("/")[-1]
            if ref_name not in used:
                used.add(ref_name)
                ref_def = definitions.get(ref_name)
                if ref_def:
                    visit_schema(ref_def)  # Ricorsione sul tipo referenziato
        # Caso array
        elif schema.get("type") == "array" and "items" in schema:
            visit_schema(schema["items"])
        # Caso oggetto inline
        elif schema.get("type") == "object":
            for prop in schema.get("properties", {}).values():
                visit_schema(prop)

    # Analizza tutti i path del WADL
    for path, methods in swagger.get("paths", {}).items():
        for method_spec in methods.values():
            # Request body
            for param in method_spec.get("parameters", []):
                if param.get("in") == "body" and "schema" in param:
                    visit_schema(param["schema"])
            # Responses
            for response in method_spec.get("responses", {}).values():
                if "schema" in response:
                    visit_schema(response["schema"])

    return used

# Resolve deep $ref chains recursively to flatten all inherited properties
def resolve_schema(schema, definitions):
    if "$ref" in schema:
        ref_name = schema["$ref"].split("/")[-1]
        resolved = definitions.get(ref_name, {})
        return resolve_schema(resolved, definitions)
    else:
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        return properties, required

# Mapping Swagger types to XSD
def map_swagger_type_to_xsd(swagger_type, swagger_format=None):
    if swagger_type == "string" and swagger_format == "date-time":
        return "dateTime"
    if swagger_type == "string" and swagger_format == "date":
        return "date"
    return {
        "string": "string",
        "integer": "int",
        "boolean": "boolean",
        "number": "decimal"
    }.get(swagger_type, "string")

def generate_xsd(definitions, used_definitions, root_elements, output_dir, swagger_file):
    schema = ET.Element(f"{{{XSD_NAMESPACE}}}schema", attrib={
        "targetNamespace": XSD_TARGET_NAMESPACE,
        "elementFormDefault": "unqualified",
        f"xmlns:{XSD_PREFIX}": XSD_TARGET_NAMESPACE
    })

    for def_name, def_body in definitions.items():
        is_used = def_name in used_definitions
        if not is_used:
            schema.append(ET.Comment(f"unused type: {def_name}"))

        complex_type = ET.SubElement(schema, f"{{{XSD_NAMESPACE}}}complexType", attrib={"name": def_name})
        sequence = ET.SubElement(complex_type, f"{{{XSD_NAMESPACE}}}sequence")

        properties = def_body.get("properties", {})
        required_fields = def_body.get("required", [])

        for prop_name, prop_attrs in properties.items():
            if "$ref" in prop_attrs:
                ref_name = prop_attrs["$ref"].split("/")[-1]
                used_definitions.add(ref_name)
                ET.SubElement(sequence, f"{{{XSD_NAMESPACE}}}element", attrib={
                    "name": prop_name,
                    "type": f"{XSD_PREFIX}:{ref_name}",
                    "minOccurs": "1" if prop_name in required_fields else "0"
                })
                continue

            swagger_type = prop_attrs.get("type")
            swagger_format = prop_attrs.get("format")

            if swagger_type == "array":
                items = prop_attrs.get("items", {})
                if "multipleOf" in items:
                    raise ValueError(f"Restriction 'multipleOf' is not supported in XSD (property '{prop_name}')")

                wrapper_el = ET.SubElement(sequence, f"{{{XSD_NAMESPACE}}}element", attrib={
                    "name": prop_name,
                    "minOccurs": "1" if prop_name in required_fields else "0"
                })
                complex_el = ET.SubElement(wrapper_el, f"{{{XSD_NAMESPACE}}}complexType")
                array_seq = ET.SubElement(complex_el, f"{{{XSD_NAMESPACE}}}sequence")

                item_type = items.get("type")
                item_format = items.get("format")
                item_el = ET.SubElement(array_seq, f"{{{XSD_NAMESPACE}}}element", attrib={
                    "name": "item",
                    "minOccurs": "0",
                    "maxOccurs": "unbounded"
                })

                if item_type in ["string", "integer", "number"] and any(k in items for k in ["minLength", "maxLength", "pattern", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"]):
                    base_xsd = f"xs:{map_swagger_type_to_xsd(item_type, item_format)}"
                    simple_type = ET.SubElement(item_el, f"{{{XSD_NAMESPACE}}}simpleType")
                    restriction = ET.SubElement(simple_type, f"{{{XSD_NAMESPACE}}}restriction", attrib={"base": base_xsd})

                    if "minLength" in items:
                        ET.SubElement(restriction, f"{{{XSD_NAMESPACE}}}minLength", value=str(items["minLength"]))
                    if "maxLength" in items:
                        ET.SubElement(restriction, f"{{{XSD_NAMESPACE}}}maxLength", value=str(items["maxLength"]))
                    if "pattern" in items:
                        ET.SubElement(restriction, f"{{{XSD_NAMESPACE}}}pattern", value=items["pattern"])

                    if "minimum" in items:
                        if items.get("exclusiveMinimum", False):
                            ET.SubElement(restriction, f"{{{XSD_NAMESPACE}}}minExclusive", value=str(items["minimum"]))
                        else:
                            ET.SubElement(restriction, f"{{{XSD_NAMESPACE}}}minInclusive", value=str(items["minimum"]))
                    if "maximum" in items:
                        if items.get("exclusiveMaximum", False):
                            ET.SubElement(restriction, f"{{{XSD_NAMESPACE}}}maxExclusive", value=str(items["maximum"]))
                        else:
                            ET.SubElement(restriction, f"{{{XSD_NAMESPACE}}}maxInclusive", value=str(items["maximum"]))
                else:
                    item_xsd_type = map_swagger_type_to_xsd(item_type, item_format)
                    item_el.set("type", f"xs:{item_xsd_type}")

            elif swagger_type == "object" and "properties" in prop_attrs:
                el = ET.SubElement(sequence, f"{{{XSD_NAMESPACE}}}element", attrib={
                    "name": prop_name,
                    "minOccurs": "1" if prop_name in required_fields else "0"
                })
                inline_complex = ET.SubElement(el, f"{{{XSD_NAMESPACE}}}complexType")
                inline_seq = ET.SubElement(inline_complex, f"{{{XSD_NAMESPACE}}}sequence")
                for sub_name, sub_attrs in prop_attrs["properties"].items():
                    sub_type = map_swagger_type_to_xsd(sub_attrs.get("type"), sub_attrs.get("format"))
                    ET.SubElement(inline_seq, f"{{{XSD_NAMESPACE}}}element", attrib={
                        "name": sub_name,
                        "type": f"xs:{sub_type}"
                    })

            elif swagger_type in ["string", "integer", "number"] and any(k in prop_attrs for k in ["minLength", "maxLength", "pattern", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf"]):
                if "multipleOf" in prop_attrs:
                    raise ValueError(f"Restriction 'multipleOf' is not supported in XSD (property '{prop_name}')")

                base_xsd = f"xs:{map_swagger_type_to_xsd(swagger_type, swagger_format)}"
                el = ET.SubElement(sequence, f"{{{XSD_NAMESPACE}}}element", attrib={
                    "name": prop_name,
                    "minOccurs": "1" if prop_name in required_fields else "0"
                })
                simple_type = ET.SubElement(el, f"{{{XSD_NAMESPACE}}}simpleType")
                restriction = ET.SubElement(simple_type, f"{{{XSD_NAMESPACE}}}restriction", attrib={"base": base_xsd})

                if "minLength" in prop_attrs:
                    ET.SubElement(restriction, f"{{{XSD_NAMESPACE}}}minLength", value=str(prop_attrs["minLength"]))
                if "maxLength" in prop_attrs:
                    ET.SubElement(restriction, f"{{{XSD_NAMESPACE}}}maxLength", value=str(prop_attrs["maxLength"]))
                if "pattern" in prop_attrs:
                    ET.SubElement(restriction, f"{{{XSD_NAMESPACE}}}pattern", value=prop_attrs["pattern"])

                if "minimum" in prop_attrs:
                    if prop_attrs.get("exclusiveMinimum", False):
                        ET.SubElement(restriction, f"{{{XSD_NAMESPACE}}}minExclusive", value=str(prop_attrs["minimum"]))
                    else:
                        ET.SubElement(restriction, f"{{{XSD_NAMESPACE}}}minInclusive", value=str(prop_attrs["minimum"]))
                if "maximum" in prop_attrs:
                    if prop_attrs.get("exclusiveMaximum", False):
                        ET.SubElement(restriction, f"{{{XSD_NAMESPACE}}}maxExclusive", value=str(prop_attrs["maximum"]))
                    else:
                        ET.SubElement(restriction, f"{{{XSD_NAMESPACE}}}maxInclusive", value=str(prop_attrs["maximum"]))

            else:
                xsd_type = map_swagger_type_to_xsd(swagger_type, swagger_format)
                ET.SubElement(sequence, f"{{{XSD_NAMESPACE}}}element", attrib={
                    "name": prop_name,
                    "type": f"xs:{xsd_type}",
                    "minOccurs": "1" if prop_name in required_fields else "0"
                })

    for def_name in sorted(root_elements):
        ET.SubElement(schema, f"{{{XSD_NAMESPACE}}}element", attrib={
            "name": def_name,
            "type": f"{XSD_PREFIX}:{def_name}"
        })

    swagger_filename = Path(swagger_file).stem
    output_file = os.path.join(output_dir, f"{swagger_filename}.xsd")
    with open(output_file, "w") as f:
        f.write(prettify_xml(schema))

    return output_file

def generate_wadl(swagger, definitions, xsd_filename, output_dir, swagger_file):
    application = ET.Element(f"{{{WADL_NAMESPACE}}}application", attrib={
        f"xmlns:{XSD_PREFIX}": XSD_TARGET_NAMESPACE,
        "xmlns:xs": XSD_NAMESPACE
    })

    grammars = ET.SubElement(application, "grammars")
    swagger_filename = Path(swagger_file).stem
    ET.SubElement(grammars, "include", href=f"{swagger_filename}.xsd")

    resources = ET.SubElement(application, "resources",
                              base=swagger.get("host", "http://localhost") + swagger.get("basePath", "/"))

    used_definitions = set()
    root_element_types = set()

    for path, methods in swagger.get("paths", {}).items():
        resource = ET.SubElement(resources, "resource", attrib={"path": path})
        for method_name, method_spec in methods.items():
            method = ET.SubElement(resource, "method", attrib={
                "name": method_name.upper()
            })
            ET.SubElement(method, "doc", attrib={"xml:lang": "en", "title": method_spec.get("operationId", "")})

            request = ET.SubElement(method, "request")
            parameters = method_spec.get("parameters", [])
            consumes = method_spec.get("consumes", [])

            for param in parameters:
                if param.get("in") == "body" and "$ref" in param.get("schema", {}):
                    ref_name = param["schema"]["$ref"].split("/")[-1]
                    used_definitions.add(ref_name)
                    root_element_types.add(ref_name)
                    for media_type in consumes or ["application/xml", "application/json"]:
                        ET.SubElement(request, "representation", attrib={
                            "mediaType": media_type,
                            "element": f"{XSD_PREFIX}:{ref_name}"
                        })
                elif param.get("in") in ["query", "path", "header"]:
                    style_map = {"query": "query", "path": "template", "header": "header"}
                    style = style_map.get(param["in"], "query")
                    param_attrs = {
                        "name": param.get("name", "param"),
                        "required": str(param.get("required", False)).lower(),
                        "style": style,
                        "type": f"xs:{map_swagger_type_to_xsd(param.get('type'), param.get('format'))}"
                    }
                    ET.SubElement(request, "param", attrib=param_attrs)

            responses = method_spec.get("responses", {})
            for code, response_spec in responses.items():
                response_el = ET.SubElement(method, "response", attrib={"status": code})
                schema_resp = response_spec.get("schema")
                ref_name = None
                if schema_resp:
                    if "$ref" in schema_resp:
                        ref_name = schema_resp["$ref"].split("/")[-1]
                    elif schema_resp.get("type") == "array" and "items" in schema_resp and "$ref" in schema_resp["items"]:
                        ref_name = schema_resp["items"]["$ref"].split("/")[-1]
                if ref_name:
                    used_definitions.add(ref_name)
                    root_element_types.add(ref_name)
                    produces = method_spec.get("produces", ["application/xml", "application/json"])
                    for media_type in produces:
                        ET.SubElement(response_el, "representation", attrib={
                            "mediaType": media_type,
                            "element": f"{XSD_PREFIX}:{ref_name}"
                        })
                else:
                    for media_type in method_spec.get("produces", ["application/xml", "application/json"]):
                        ET.SubElement(response_el, "representation", attrib={"mediaType": media_type})

    wadl_filename = os.path.join(output_dir, f"{swagger_filename}.wadl")
    with open(wadl_filename, "w") as f:
        f.write(prettify_xml(application))

    return wadl_filename, root_element_types

def main():
    parser = argparse.ArgumentParser(description="Convert Swagger 2.0 JSON to WADL + XSD.")
    parser.add_argument("swagger_file", help="Input Swagger JSON file")
    parser.add_argument("--output-dir", help="Output directory", default=".")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    with open(args.swagger_file, "r") as f:
        swagger = json.load(f)

    definitions = swagger.get("definitions", {})

    # Passaggio 1: raccoglie tutti i tipi usati (anche profondamente)
    used_definitions = collect_used_definitions_from_wadl(swagger, definitions)

    # Passaggio 2: genera WADL e ottiene anche i root_elements usati direttamente come elementi globali
    xsd_filename = None  # inizializza per sicurezza
    wadl_filename, root_elements = generate_wadl(swagger, definitions, None, args.output_dir, args.swagger_file)

    # Passaggio 3: genera XSD con info su quali definizioni sono usate e quali sono root
    xsd_filename = generate_xsd(definitions, used_definitions, root_elements, args.output_dir, args.swagger_file)

    print(f"Generated WADL: {wadl_filename}")
    print(f"Generated XSD : {xsd_filename}")

if __name__ == "__main__":
    main()
