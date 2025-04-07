# swagger2wadl.py
# Author: ChatGPT (with user's collaboration)
# Purpose: Convert a Swagger 2.0 (JSON format) file into a WADL file and related XSD.
# Features:
# - Extracts Swagger definitions to build the XSD schema
# - Generates a WADL file that references the XSD via namespace and include
# - Supports pretty-printed XML output and command line usage

import json
import os
import argparse
import xml.etree.ElementTree as ET
from xml.dom import minidom

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
    """
    Makes the XML output indented and human-readable.
    """
    rough_string = ET.tostring(elem, 'utf-8')
    reparsed = minidom.parseString(rough_string)
    return reparsed.toprettyxml(indent="  ")

def parse_swagger(swagger):
    """
    Extracts the 'definitions' section from the Swagger JSON.
    """
    definitions = swagger.get("definitions", {})
    return definitions

def generate_xsd(definitions):
    """
    Converts Swagger definitions to an XSD schema.

    Parameters:
    definitions (dict): Swagger model definitions

    Returns:
    xml.etree.ElementTree.Element: Root XML element of the schema
    """
    schema = ET.Element(f"{{{XSD_NAMESPACE}}}schema", attrib={
        "targetNamespace": XSD_TARGET_NAMESPACE,
        "elementFormDefault": "unqualified",
        f"xmlns:{XSD_PREFIX}": XSD_TARGET_NAMESPACE
    })

    for def_name, def_body in definitions.items():
        # Create a global element for each top-level type
        ET.SubElement(schema, f"{{{XSD_NAMESPACE}}}element", attrib={
            "name": def_name,
            "type": f"{XSD_PREFIX}:{def_name}"
        })

        # Create the corresponding complex type
        complex_type = ET.SubElement(schema, f"{{{XSD_NAMESPACE}}}complexType", name=def_name)
        sequence = ET.SubElement(complex_type, f"{{{XSD_NAMESPACE}}}sequence")

        required_fields = def_body.get("required", [])
        properties = def_body.get("properties", {})
        for prop_name, prop_attrs in properties.items():
            xsd_type = map_swagger_type_to_xsd(prop_attrs.get("type"))
            # Add each property as an element in the sequence
            ET.SubElement(sequence, f"{{{XSD_NAMESPACE}}}element", attrib={
                "name": prop_name,
                "type": f"xs:{xsd_type}",
                "minOccurs": "1" if prop_name in required_fields else "0"
            })

    return schema

def map_swagger_type_to_xsd(swagger_type):
    """
    Maps basic Swagger types to their XSD equivalents.

    Parameters:
    swagger_type (str): Swagger type string

    Returns:
    str: Corresponding XSD type string
    """
    return {
        "string": "string",
        "integer": "int",
        "boolean": "boolean",
        "number": "decimal"
    }.get(swagger_type, "string")

def generate_wadl(swagger, definitions, xsd_filename):
    """
    Generates a WADL XML structure from a Swagger object and XSD reference.

    Parameters:
    swagger (dict): Parsed Swagger JSON
    definitions (dict): Swagger definitions
    xsd_filename (str): Filename of the associated XSD schema

    Returns:
    xml.etree.ElementTree.Element: Root WADL XML element
    """
    application = ET.Element(f"{{{WADL_NAMESPACE}}}application")

    # Grammars section referencing the XSD
    grammars = ET.SubElement(application, "grammars")
    ET.SubElement(grammars, "include", href=xsd_filename)

    # Add declaration for namespace "tns"
    application.set(f"xmlns:{XSD_PREFIX}", XSD_TARGET_NAMESPACE)

    # Create the resources section
    resources = ET.SubElement(application, "resources", base=swagger.get("host", "http://localhost") + swagger.get("basePath", "/"))

    paths = swagger.get("paths", {})
    for path, methods in paths.items():
        resource = ET.SubElement(resources, "resource", path=path)
        for method_name, method_spec in methods.items():
            method = ET.SubElement(resource, "method", name=method_name.upper())
            response = ET.SubElement(method, "response")

            # Add representations for each response type
            for code, response_spec in method_spec.get("responses", {}).items():
                schema_ref = response_spec.get("schema", {}).get("$ref")
                if schema_ref:
                    ref_name = schema_ref.split("/")[-1]
                    for media_type in ["application/xml", "application/json"]:
                        ET.SubElement(response, "representation", mediaType=media_type, element=f"{XSD_PREFIX}:{ref_name}")

    return application

def save_pretty_xml(element, filename):
    """
    Saves an XML element to a file with indentation.

    Parameters:
    element (Element): The XML root element
    filename (str): Output file path
    """
    pretty_xml = prettify_xml(element)
    with open(filename, "w", encoding="utf-8") as f:
        f.write(pretty_xml)

def main():
    """
    Main entry point for the command-line script. Handles parsing input
    arguments, loading the Swagger file, generating the XSD and WADL,
    and writing the resulting files.
    """
    parser = argparse.ArgumentParser(description="Convert Swagger 2.0 JSON to WADL + XSD.")
    parser.add_argument("swagger_file", help="Path to the Swagger JSON file")
    parser.add_argument("--output-dir", default=".", help="Directory to save WADL and XSD files (default: current folder)")
    args = parser.parse_args()

    swagger_filename = os.path.splitext(os.path.basename(args.swagger_file))[0]
    wadl_filename = f"{swagger_filename}.wadl"
    xsd_filename = f"{swagger_filename}.xsd"

    # Load the Swagger file
    with open(args.swagger_file, "r", encoding="utf-8") as f:
        swagger = json.load(f)

    definitions = parse_swagger(swagger)
    xsd = generate_xsd(definitions)
    wadl = generate_wadl(swagger, definitions, xsd_filename)

    # Save the XML files
    save_pretty_xml(xsd, os.path.join(args.output_dir, xsd_filename))
    save_pretty_xml(wadl, os.path.join(args.output_dir, wadl_filename))

    print(f"Generated files:\n- {xsd_filename}\n- {wadl_filename}")

if __name__ == "__main__":
    main()
