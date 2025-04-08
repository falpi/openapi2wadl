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

def generate_xsd(definitions, used_definitions, output_dir, swagger_file):
    schema = ET.Element(f"{{{XSD_NAMESPACE}}}schema", attrib={
        "targetNamespace": XSD_TARGET_NAMESPACE,
        "elementFormDefault": "unqualified",
        f"xmlns:{XSD_PREFIX}": XSD_TARGET_NAMESPACE
    })

    complex_types = []
    element_defs = []

    for def_name, def_body in definitions.items():
        is_used = def_name in used_definitions

        if not is_used:
            complex_types.append(ET.Comment(f"unused type: {def_name}"))

        complex_type = ET.Element(f"{{{XSD_NAMESPACE}}}complexType", name=def_name)
        sequence = ET.SubElement(complex_type, f"{{{XSD_NAMESPACE}}}sequence")
        required_fields = def_body.get("required", [])
        properties = def_body.get("properties", {})

        for prop_name, prop_attrs in properties.items():
            swagger_type = prop_attrs.get("type")
            swagger_format = prop_attrs.get("format")

            if swagger_type == "array":
                items = prop_attrs.get("items", {})
                item_type = map_swagger_type_to_xsd(items.get("type"), items.get("format"))
                wrapper_el = ET.SubElement(sequence, f"{{{XSD_NAMESPACE}}}element", attrib={
                    "name": prop_name,
                    "minOccurs": "1" if prop_name in required_fields else "0"
                })
                complex_el = ET.SubElement(wrapper_el, f"{{{XSD_NAMESPACE}}}complexType")
                array_seq = ET.SubElement(complex_el, f"{{{XSD_NAMESPACE}}}sequence")
                ET.SubElement(array_seq, f"{{{XSD_NAMESPACE}}}element", attrib={
                    "name": "item",
                    "type": f"xs:{item_type}",
                    "minOccurs": "0",
                    "maxOccurs": "unbounded"
                })

            elif swagger_type == "string" and swagger_format in ["date", "date-time"]:
                xsd_type = map_swagger_type_to_xsd(swagger_type, swagger_format)
                ET.SubElement(sequence, f"{{{XSD_NAMESPACE}}}element", attrib={
                    "name": prop_name,
                    "type": f"xs:{xsd_type}",
                    "minOccurs": "1" if prop_name in required_fields else "0"
                })

            elif swagger_type == "string" and any(k in prop_attrs for k in ["minLength", "maxLength", "pattern"]):
                el = ET.SubElement(sequence, f"{{{XSD_NAMESPACE}}}element", attrib={
                    "name": prop_name,
                    "minOccurs": "1" if prop_name in required_fields else "0"
                })
                simple_type = ET.SubElement(el, f"{{{XSD_NAMESPACE}}}simpleType")
                restriction = ET.SubElement(simple_type, f"{{{XSD_NAMESPACE}}}restriction", attrib={
                    "base": "xs:string"
                })
                if "minLength" in prop_attrs:
                    ET.SubElement(restriction, f"{{{XSD_NAMESPACE}}}minLength", value=str(prop_attrs["minLength"]))
                if "maxLength" in prop_attrs:
                    ET.SubElement(restriction, f"{{{XSD_NAMESPACE}}}maxLength", value=str(prop_attrs["maxLength"]))
                if "pattern" in prop_attrs:
                    ET.SubElement(restriction, f"{{{XSD_NAMESPACE}}}pattern", value=prop_attrs["pattern"])

            else:
                xsd_type = map_swagger_type_to_xsd(swagger_type, swagger_format)
                ET.SubElement(sequence, f"{{{XSD_NAMESPACE}}}element", attrib={
                    "name": prop_name,
                    "type": f"xs:{xsd_type}",
                    "minOccurs": "1" if prop_name in required_fields else "0"
                })

        complex_types.append(complex_type)

        if is_used:
            element_defs.append((def_name, def_name))

    for complex_type in complex_types:
        schema.append(complex_type)

    for def_name, type_name in element_defs:
        ET.SubElement(schema, f"{{{XSD_NAMESPACE}}}element", attrib={
            "name": def_name,
            "type": f"{XSD_PREFIX}:{type_name}"
        })

    # Determine output file name based on input Swagger file name
    swagger_filename =  Path(swagger_file).stem
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
    
    swagger_filename =  Path(swagger_file).stem    
    ET.SubElement(grammars, "include", href=f"{Path(swagger_file).stem}.xsd")

    resources = ET.SubElement(application, "resources", base=swagger.get("host", "http://localhost") + swagger.get("basePath", "/"))
    used_definitions = set()

    paths = swagger.get("paths", {})
    for path, methods in paths.items():
        resource = ET.SubElement(resources, "resource", path=path)
        for method_name, method_spec in methods.items():
            method = ET.SubElement(resource, "method", name=method_name.upper())

            request = None
            for param in method_spec.get("parameters", []):
                if request is None:
                    request = ET.SubElement(method, "request")

                if param.get("in") == "body" and "$ref" in param.get("schema", {}):
                    ref_name = param["schema"]["$ref"].split("/")[-1]
                    used_definitions.add(ref_name)
                    for media_type in ["application/xml", "application/json"]:
                        ET.SubElement(request, "representation", mediaType=media_type, element=f"{XSD_PREFIX}:{ref_name}")
                else:
                    param_in = param.get("in")
                    param_attrs = {
                        "name": param.get("name", "param"),
                        "required": str(param.get("required", False)).lower()
                    }
                    if param_in == "query":
                        param_attrs["style"] = "query"
                    elif param_in == "path":
                        param_attrs["style"] = "template"
                    elif param_in == "header":
                        param_attrs["style"] = "header"
                    else:
                        continue
                    if "type" in param:
                        param_attrs["type"] = f"xs:{map_swagger_type_to_xsd(param['type'], param.get('format'))}"
                    ET.SubElement(request, "param", param_attrs)

            response = ET.SubElement(method, "response")
            for code, response_spec in method_spec.get("responses", {}).items():
                schema = response_spec.get("schema")
                if not schema:
                    continue
                if "$ref" in schema:
                    ref_name = schema["$ref"].split("/")[-1]
                    used_definitions.add(ref_name)
                    for media_type in ["application/xml", "application/json"]:
                        ET.SubElement(response, "representation", mediaType=media_type, element=f"{XSD_PREFIX}:{ref_name}")

    # Determine WADL output filename based on Swagger input
    swagger_filename =  Path(swagger_file).stem
    output_file = os.path.join(output_dir, f"{swagger_filename}.wadl")
    with open(output_file, "w") as f:
        f.write(prettify_xml(application))

    return output_file

# Main function to execute the conversion
def main():
    parser = argparse.ArgumentParser(description="Convert Swagger JSON to WADL and XSD.")
    parser.add_argument("swagger_file", help="Path to the Swagger JSON file")
    parser.add_argument("output_dir", help="Directory to save WADL and XSD files", nargs="?", default="")  # Optional output dir
    args = parser.parse_args()

    # Load Swagger JSON
    with open(args.swagger_file, "r") as f:
        swagger = json.load(f)

    # Parse definitions from Swagger
    definitions = parse_swagger(swagger)

    # Generate XSD file
    xsd_filename = generate_xsd(definitions, definitions.keys(), args.output_dir, args.swagger_file)
    print(f"Generated XSD: {xsd_filename}")

    # Generate WADL file
    wadl_filename = generate_wadl(swagger, definitions, xsd_filename, args.output_dir, args.swagger_file)
    print(f"Generated WADL: {wadl_filename}")

if __name__ == "__main__":
    main()
