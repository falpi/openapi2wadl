#!/usr/bin/env python3
# openapi2wadl.py
# Converts Swagger 2.0 or OpenAPI 3.0 into WADL + XSD

import os
import re
import json
import argparse
import xml.etree.ElementTree as ET
from xml.dom import minidom

XSD_NAMESPACE = "http://www.w3.org/2001/XMLSchema"
WADL_NAMESPACE = "http://wadl.dev.java.net/2009/02"
XSD_TARGET_NAMESPACE = "http://example.com/schema"
XSD_PREFIX = "tns"

ET.register_namespace("xs", XSD_NAMESPACE)
ET.register_namespace("", WADL_NAMESPACE)
ET.register_namespace(XSD_PREFIX, XSD_TARGET_NAMESPACE)

# Manipola gli XML dello XSD e WADL
def prettify_xml(elem):
    """Return a pretty-printed XML string with corrected name attribute spacing."""
    rough_string = ET.tostring(elem, 'utf-8')
    reparsed = minidom.parseString(rough_string)
    pretty = reparsed.toprettyxml(indent="  ")

    # Correggi solo gli attributi name con spazi interni
    fixed = re.sub(r'name="([A-Za-z0-9_]+)(\s+)"', r'name="\1"\2', pretty)

    # Sposta in fondo minOccurs e maxOccurs sugli "element"
    fixed = re.sub(r'<(.+?)(?=\sminOccurs)(\sminOccurs="[^"]*")([^\/|>]*)(\/)?>', r'<\1\3\2\4>', fixed)
    fixed = re.sub(r'<(.+?)(?=\smaxOccurs)(\smaxOccurs="[^"]*")([^\/|>]*)(\/)?>', r'<\1\3\2\4>', fixed)

    # Sposta in fondo id su "method"
    fixed = re.sub(r'<(method)(\sid="[^"]*")([^\/|>]*)(\/)?>', r'<\1\3\2\4>', fixed)

    return fixed

# Rileva la versione della specifica
def detect_version(spec):
    if "swagger" in spec and spec["swagger"] == "2.0":
        return "swagger2"
    elif "openapi" in spec and spec["openapi"].startswith("3."):
        return "openapi3"
    else:
        raise ValueError("Unsupported OpenAPI/Swagger version")

def extract_restrictions(props):
    return {
        k: props[k]
        for k in [
            "minLength", "maxLength", "pattern",
            "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"
        ] if k in props
    }

# Estrare la definizione dei tipi 
def extract_root_definitions(spec, version):
    if version == "swagger2":
        return spec.get("definitions", {})
    else:
        return spec.get("components", {}).get("schemas", {})

# Determina tutti i tipi effettivamente utilizzati
def extract_used_definitions(spec, version, root_definitions):
    """
    Analizza lo spec e raccoglie ricorsivamente tutti i nomi delle definizioni referenziate,
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
                ref_def = root_definitions.get(ref_name)
                if ref_def:
                    visit_schema(ref_def)  # Ricorsione sul tipo referenziato
        # Caso array
        elif schema.get("type") == "array" and "items" in schema:
            visit_schema(schema["items"])
        # Caso oggetto inline
        elif schema.get("type") == "object":
            for prop in schema.get("properties", {}).values():
                visit_schema(prop)

    # Analizza tutti i path 
    for path, methods in spec.get("paths", {}).items():
        for method_spec in methods.values():
        
            if version == "swagger2":
                # Request body
                for param in method_spec.get("parameters", []):
                    if param.get("in") == "body" and "schema" in param:
                        visit_schema(param["schema"])
                # Responses
                for response in method_spec.get("responses", {}).values():
                    if "schema" in response:
                        visit_schema(response["schema"])
                        
            if version == "openapi3":
                # Request body
                for content in method_spec.get("requestBody",{}).get("content", {}).values():
                    if "schema" in content:
                       visit_schema(content["schema"])
                        
                # Responses
                for response in method_spec.get("responses", {}).values():
                    for content in response.get("content", {}).values():
                        visit_schema(content["schema"])

    return used
    
def apply_restrictions(restriction_elem, restrictions):
    if "minLength" in restrictions:
        ET.SubElement(restriction_elem, f"{{{XSD_NAMESPACE}}}minLength", value=str(restrictions["minLength"]))
    if "maxLength" in restrictions:
        ET.SubElement(restriction_elem, f"{{{XSD_NAMESPACE}}}maxLength", value=str(restrictions["maxLength"]))
    if "pattern" in restrictions:
        ET.SubElement(restriction_elem, f"{{{XSD_NAMESPACE}}}pattern", value=restrictions["pattern"])
    if "minimum" in restrictions:
        ET.SubElement(restriction_elem, f"{{{XSD_NAMESPACE}}}minInclusive", value=str(restrictions["minimum"]))
    if "maximum" in restrictions:
        ET.SubElement(restriction_elem, f"{{{XSD_NAMESPACE}}}maxInclusive", value=str(restrictions["maximum"]))
    if "exclusiveMinimum" in restrictions:
        ET.SubElement(restriction_elem, f"{{{XSD_NAMESPACE}}}minExclusive", value=str(restrictions["exclusiveMinimum"]))
    if "exclusiveMaximum" in restrictions:
        ET.SubElement(restriction_elem, f"{{{XSD_NAMESPACE}}}maxExclusive", value=str(restrictions["exclusiveMaximum"]))

def map_integer_type_with_special_case(swagger_type, swagger_format, restrictions):
    if swagger_type == "integer":
        min_ = restrictions.get("minimum")
        max_ = restrictions.get("maximum")

        if min_ == 0 and max_ == 2147483647:
            return "nonNegativeInteger"
        elif min_ == 1 and max_ == 2147483647:
            return "positiveInteger"

    return None  # fallback to manual restriction

# Mapping Swagger types to XSD
def map_swagger_type_to_xsd(swagger_type, swagger_format=None):
    # Support direct type mapping (type = "date", "date-time")
    if swagger_type in ["date", "date-time"]:
        return "dateTime" if swagger_type == "date-time" else "date"

    # Support format-based mapping (string + format)
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

def build_string_type_name(restrictions):
    min_len = restrictions.get("minLength", 0)
    max_len = restrictions.get("maxLength", "")

    if min_len == 0: 
        return f"string{max_len}TypeNillable"
    elif min_len == 1 and isinstance(max_len, int):
        return f"string{max_len}Type"
    elif isinstance(min_len, int) and isinstance(max_len, int):
        return f"string{min_len}to{max_len}Type"
    else:
        return f"string{min_len}to{max_len}Type"
        
def resolve_ref(schema, root_definitions, seen=None):
    """Risoluzione ricorsiva di $ref, evita cicli e unisce le proprietà."""
    if not isinstance(schema, dict):
        return schema

    if "$ref" in schema:
        ref = schema["$ref"]
        ref_name = ref.split("/")[-1]
        if seen is None:
            seen = set()
        if ref_name in seen:
            return {}  # evitiamo loop
        seen.add(ref_name)

        resolved = root_definitions.get(ref_name, {}).copy()
        nested = resolve_ref(resolved, root_definitions, seen)
        return {**nested, **schema}  # priorità a schema locale

    return schema
    
# Genera il file XSD
def generate_xsd(root_definitions,used_definitions,wadl_definitions):

    schema = ET.Element(f"{{{XSD_NAMESPACE}}}schema", attrib={
        "targetNamespace": XSD_TARGET_NAMESPACE,
        "elementFormDefault": "unqualified",
        f"xmlns:{XSD_PREFIX}": XSD_TARGET_NAMESPACE
    })

    complex_types = []
    element_declarations = []
    string_restriction_registry = {}

    for idx, (def_name, def_body) in enumerate(root_definitions.items()):
    
        def_body = resolve_ref(def_body, root_definitions)  # risolvi $ref se presente

        complex_type = ET.Element(f"{{{XSD_NAMESPACE}}}complexType", name=def_name)
        
        sequence = ET.SubElement(complex_type, f"{{{XSD_NAMESPACE}}}sequence")
        required_fields = def_body.get("required", [])
        properties = def_body.get("properties", {})

        name_lengths = [
            len(p) for p, a in properties.items() if a.get("type") != "array"
        ]
        max_name_len = max(name_lengths or [0])

        for prop_name, prop_attrs in properties.items():
            prop_attrs = resolve_ref(prop_attrs, root_definitions)
            swagger_type = prop_attrs.get("type")
            swagger_format = prop_attrs.get("format")
            restrictions = extract_restrictions(prop_attrs)

            if swagger_type == "array":
                items = prop_attrs.get("items", {})
                items = resolve_ref(items, root_definitions)

                item_type = items.get("type")
                item_format = items.get("format")
                item_restrictions = extract_restrictions(items)

                wrapper_attrib = {"name": prop_name}
                if prop_name not in required_fields:
                    wrapper_attrib["minOccurs"] = "0"
                wrapper_el = ET.SubElement(sequence, f"{{{XSD_NAMESPACE}}}element", attrib=wrapper_attrib)

                complex_array = ET.SubElement(wrapper_el, f"{{{XSD_NAMESPACE}}}complexType")
                array_seq = ET.SubElement(complex_array, f"{{{XSD_NAMESPACE}}}sequence")
                item_el = ET.SubElement(array_seq, f"{{{XSD_NAMESPACE}}}element", attrib={
                    "name": "item",
                    "minOccurs": "0",
                    "maxOccurs": "unbounded"
                })

                if "$ref" in prop_attrs.get("items", {}):
                    ref_name = prop_attrs["items"]["$ref"].split("/")[-1]
                    item_el.set("type", f"{XSD_PREFIX}:{ref_name}")

                elif item_type:
                    simplified = map_integer_type_with_special_case(item_type, item_format, item_restrictions)
                    if simplified:
                        item_el.set("type", f"xs:{simplified}")
                    elif item_type == "string" and ("minLength" in item_restrictions or "maxLength" in item_restrictions):
                        type_name = build_string_type_name(item_restrictions)
                        item_el.set("type", f"{XSD_PREFIX}:{type_name}")
                        string_restriction_registry[type_name] = item_restrictions
                    elif item_restrictions:
                        simple_type = ET.SubElement(item_el, f"{{{XSD_NAMESPACE}}}simpleType")
                        restriction = ET.SubElement(simple_type, f"{{{XSD_NAMESPACE}}}restriction",
                                                    base=f"xs:{map_swagger_type_to_xsd(item_type, item_format)}")
                        apply_restrictions(restriction, item_restrictions)
                    else:
                        item_el.set("type", f"xs:{map_swagger_type_to_xsd(item_type, item_format)}")
                        
            else:
                base_attrib = {"name": prop_name}
                simplified = map_integer_type_with_special_case(swagger_type, swagger_format, restrictions)
                if simplified:
                    base_attrib["type"] = f"xs:{simplified}"
                elif swagger_type == "string" and ("minLength" in restrictions or "maxLength" in restrictions):
                    type_name = build_string_type_name(restrictions)
                    base_attrib["type"] = f"{XSD_PREFIX}:{type_name}"
                    string_restriction_registry[type_name] = restrictions
                elif "$ref" in prop_attrs:
                    ref_name = prop_attrs["$ref"].split("/")[-1]
                    base_attrib["type"] = f"{XSD_PREFIX}:{ref_name}"
                elif restrictions:
                    pass
                else:
                    base_attrib["type"] = f"xs:{map_swagger_type_to_xsd(swagger_type, swagger_format)}"

                if "type" in base_attrib:
                    padding = max_name_len - len(prop_name)
                    base_attrib["name"] = prop_name + (" " * padding)

                el = ET.Element(f"{{{XSD_NAMESPACE}}}element", attrib=base_attrib)

                if restrictions and "type" not in base_attrib:
                    simple_type = ET.SubElement(el, f"{{{XSD_NAMESPACE}}}simpleType")
                    restriction = ET.SubElement(simple_type, f"{{{XSD_NAMESPACE}}}restriction",
                                                base=f"xs:{map_swagger_type_to_xsd(swagger_type, swagger_format)}")
                    apply_restrictions(restriction, restrictions)

                if prop_name not in required_fields:
                    el.attrib["minOccurs"] = "0"

                sequence.append(el)

        if not def_name in used_definitions:
            complex_types.append(ET.Comment(f" #unused# "))
        elif idx > 0:
            complex_types.append(ET.Comment(" ~~~~~~~~ "))
                
        complex_types.append(complex_type)
        if def_name in wadl_definitions:
            element_declarations.append(def_name)

    # ~~~ SimpleTypes
    schema.append(ET.Comment("#" * 100))
    schema.append(ET.Comment(" SimpleTypes "))
    schema.append(ET.Comment("#" * 100))

    sorted_simpletypes = sorted(
        string_restriction_registry.items(),
        key=lambda item: item[1].get("maxLength", float('inf'))
    )

    for idx, (type_name, restrictions) in enumerate(sorted_simpletypes):
        if idx > 0:
            schema.append(ET.Comment(" ~~~~~~~~ "))
        simple_type = ET.Element(f"{{{XSD_NAMESPACE}}}simpleType", name=type_name)
        restriction = ET.SubElement(simple_type, f"{{{XSD_NAMESPACE}}}restriction", base="xs:string")
        apply_restrictions(restriction, restrictions)
        schema.append(simple_type)

    # ~~~ ComplexTypes
    schema.append(ET.Comment("#" * 100))
    schema.append(ET.Comment(" ComplexTypes "))
    schema.append(ET.Comment("#" * 100))

    for ct in complex_types:
        schema.append(ct)

    # ~~~ Elements
    schema.append(ET.Comment("#" * 100))
    schema.append(ET.Comment(" Elements "))
    schema.append(ET.Comment("#" * 100))

    for def_name in element_declarations:
        ET.SubElement(schema, f"{{{XSD_NAMESPACE}}}element", attrib={
            "name": def_name,
            "type": f"{XSD_PREFIX}:{def_name}"
        })

    return schema

def generate_wadl(spec,version,root_definitions,wadl_definitions,xsd_filename):
    
    application = ET.Element(f"{{{WADL_NAMESPACE}}}application", attrib={
        "xmlns:xs": XSD_NAMESPACE,
        f"xmlns:{XSD_PREFIX}": XSD_TARGET_NAMESPACE
    })
    
    # ~~~ Grammars
    application.append(ET.Comment("#" * 100))
    application.append(ET.Comment(" Grammars "))
    application.append(ET.Comment("#" * 100))    
    gram = ET.SubElement(application, "grammars")
    ET.SubElement(gram, "include", href=os.path.basename(xsd_filename))

    # ~~~ Resources
    application.append(ET.Comment("#" * 100))
    application.append(ET.Comment(" Resources "))
    application.append(ET.Comment("#" * 100))
    resources = ET.SubElement(application, "resources", base=spec.get("servers", [{}])[0].get("url", "/") if version == "openapi3" else "")

    for idx, (path, methods) in enumerate(spec.get("paths", {}).items()):
        if idx > 0:
           resources.append(ET.Comment(" ~~~~~~~~ "))
        resource = ET.SubElement(resources, "resource", path=path)
        for method_name, method_def in methods.items():
            operationId = method_def.get("operationId","")
            if operationId=="":
                method = ET.SubElement(resource, "method", name=method_name.upper())
            else:
                method = ET.SubElement(resource, "method", name=method_name.upper(),id=operationId)            
            
            request = ET.SubElement(method, "request")
            parameters = method_def.get("parameters", [])
            consumes = method_def.get("consumes", [])

            if version == "openapi3" and "requestBody" in method_def:
                content = method_def["requestBody"].get("content", {})
                for mt, body_def in content.items():
                    schema_ref = body_def.get("schema", {}).get("$ref")
                    if schema_ref:
                        type_name = schema_ref.split("/")[-1]
                        wadl_definitions.add(type_name)
                        ET.SubElement(request, "representation", mediaType=mt, element=f"{XSD_PREFIX}:{type_name}")

            for param in parameters:
                param_name = param["name"]
                param_in = param.get("in", "query")
                
                # Fix: mapping Swagger "in" to WADL "style"
                if param_in == "path":
                    param_style = "template"
                elif param_in in ["query", "header", "matrix"]:
                    param_style = param_in
                elif version == "swagger2" and param_in=="body" and "$ref" in param.get("schema", {}):
                    type_name = param["schema"]["$ref"].split("/")[-1]
                    for mt in consumes:
                        wadl_definitions.add(type_name)
                        ET.SubElement(request, "representation", mediaType=mt, element=f"{XSD_PREFIX}:{type_name}")
                    continue
                else:
                    continue  # Unsupported param location

                param_type = map_swagger_type_to_xsd(param.get("type", "string"), param.get("format"))
                ET.SubElement(request, "param", name=param_name, style=param_style, type=f"xs:{param_type}", required=str(param.get("required", False)).lower())

            responses = method_def.get("responses", {})
            for status, response in responses.items():
                response_el = ET.SubElement(method, "response", status=status)
                contents = response.get("content", {}) if version == "openapi3" else {"application/json": response}
                for mt, content_def in contents.items():
                    schema = content_def.get("schema", {})
                    if "$ref" in schema:
                        type_name = schema["$ref"].split("/")[-1]
                        wadl_definitions.add(type_name)
                        ET.SubElement(response_el, "representation", mediaType=mt, element=f"{XSD_PREFIX}:{type_name}")
                    else:
                        ET.SubElement(response_el, "representation", mediaType=mt)

    return application

def main():
    parser = argparse.ArgumentParser(description="Convert Swagger 2.0 or OpenAPI 3.0 JSON to WADL + XSD")
    parser.add_argument("swagger_file", help="Path to Swagger/OpenAPI JSON file")
    parser.add_argument("--output-dir", default=".", help="Directory to save WADL and XSD files")
    args = parser.parse_args()

    # Carica il file json del descrittore di input
    with open(args.swagger_file, "r", encoding="utf-8") as f:
        spec = json.load(f)

    # Prepara i nomi dei file di output
    filename_base = os.path.splitext(os.path.basename(args.swagger_file))[0]
    xsd_filename = f"{filename_base}.xsd"
    wadl_filename = f"{filename_base}.wadl"

    # Rileva versione (Swagger/OpenApi2 o OpenApi 3)
    version = detect_version(spec)
    
    # Prepara definizione tipi
    wadl_definitions = set()
    root_definitions = extract_root_definitions(spec, version)
    used_definitions = extract_used_definitions(spec, version, root_definitions)
    
    # Generazione del WADL
    wadl_tree = generate_wadl(spec,version,root_definitions,wadl_definitions,xsd_filename)

    # Generazione XSD 
    xsd_tree = generate_xsd(root_definitions,used_definitions,wadl_definitions)

    # Scrittura file XSD
    with open(os.path.join(args.output_dir, xsd_filename), "w", encoding="utf-8") as f:
        f.write(prettify_xml(xsd_tree))

    # Scrittura file WADL
    with open(os.path.join(args.output_dir, wadl_filename), "w", encoding="utf-8") as f:
        f.write(prettify_xml(wadl_tree))

    print(f"Generated WADL: {wadl_filename}")
    print(f"Generated XSD: {xsd_filename}")

if __name__ == "__main__":
    main()
