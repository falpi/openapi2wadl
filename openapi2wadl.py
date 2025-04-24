#!/usr/bin/env python3
# openapi2wadl.py
# Converts Swagger 2.0 or OpenAPI 3.0 into WADL + XSD

# ####################################################################################################
# Referenze
# ####################################################################################################

import os
import re
import json
import argparse
import xml.etree.ElementTree as ET
from xml.dom import minidom

# ####################################################################################################
# Definizione dei namespace
# ####################################################################################################

XSD_PREFIX = "xsd"
XSD_NAMESPACE = "http://www.w3.org/2001/XMLSchema"

WADL_PREFIX = ""
WADL_NAMESPACE = "http://wadl.dev.java.net/2009/02"

TARGET_PREFIX = "tns"
TARGET_NAMESPACE = "http://example.com/schema"

ET.register_namespace(XSD_PREFIX, XSD_NAMESPACE)
ET.register_namespace(WADL_PREFIX, WADL_NAMESPACE)
ET.register_namespace(TARGET_PREFIX, TARGET_NAMESPACE)

# ####################################################################################################
# Migliorare leggibilità xml
# ####################################################################################################
def prettify_xml(elem):

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

    # Rimuove eventuali spazi finali dell'elemento
    fixed = re.sub(r'"\s*>', r'">', fixed)

    return fixed

# ####################################################################################################
# Rileva la versione della specifica
# ####################################################################################################
def detect_version(spec):

    if "swagger" in spec and spec["swagger"] == "2.0":
        return "swagger2"
    elif "openapi" in spec and spec["openapi"].startswith("3."):
        return "openapi3"
    else:
        raise ValueError("Unsupported OpenAPI/Swagger version")

# ####################################################################################################
# Estrare la definizione dei tipi di primo livello
# ####################################################################################################
def extract_root_definitions(spec, version):

    if version == "swagger2":
        return spec.get("definitions", {})
    else:
        return spec.get("components", {}).get("schemas", {})

# ####################################################################################################
# Estrae ricorsivamente le definizioni dei tipi referenziati in cascata a partire dai
# tipi dell'interfaccia di request, inclusi quelli annidati via $ref in oggetti o array.
# ####################################################################################################
def extract_used_definitions(spec, version, root_definitions):

    used_definitions = set()

    # ================================================================================================
    # Support function
    # ================================================================================================
    def visit_schema(schema):
        
        if not isinstance(schema, dict):
            return
            
        # Caso $ref
        if "$ref" in schema:
            type_name = schema["$ref"].split("/")[-1]
            if type_name not in used_definitions:
                used_definitions.add(type_name)
                type_def = root_definitions.get(type_name)
                if type_def:
                    visit_schema(type_def)  # Ricorsione sul tipo referenziato
                    
        # Caso array
        elif schema.get("type") == "array" and "items" in schema:
            visit_schema(schema["items"])
            
        # Caso oggetto inline
        elif schema.get("type") == "object":
            for properties in schema.get("properties", {}).values():
                visit_schema(properties)

    # ================================================================================================
    # Function body
    # ================================================================================================
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
                    visit_schema(content["schema"])
                        
                # Responses
                for response in method_spec.get("responses", {}).values():
                    for content in response.get("content", {}).values():
                        visit_schema(content["schema"])

    return used_definitions    

# ####################################################################################################
# Acquisce le restrizioni dalle proprietà dal swagger/openapi
# ####################################################################################################
def get_restrictions(properties):
    return {
        k: properties[k]
        for k in [
            "minLength", "maxLength", "pattern",
            "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"
        ] if k in properties
    }
    
# ####################################################################################################
# Esegue mapping delle restrizioni da swagger/openapi a XSD
# ####################################################################################################
def map_restrictions(element, restrictions):

    if "minLength" in restrictions:
        ET.SubElement(element, f"{{{XSD_NAMESPACE}}}minLength", value=str(restrictions["minLength"]))
    if "maxLength" in restrictions:
        ET.SubElement(element, f"{{{XSD_NAMESPACE}}}maxLength", value=str(restrictions["maxLength"]))
    if "pattern" in restrictions:
        ET.SubElement(element, f"{{{XSD_NAMESPACE}}}pattern", value=restrictions["pattern"])
    if "minimum" in restrictions:
        ET.SubElement(element, f"{{{XSD_NAMESPACE}}}minInclusive", value=str(restrictions["minimum"]))
    if "maximum" in restrictions:
        ET.SubElement(element, f"{{{XSD_NAMESPACE}}}maxInclusive", value=str(restrictions["maximum"]))
    if "exclusiveMinimum" in restrictions:
        ET.SubElement(element, f"{{{XSD_NAMESPACE}}}minExclusive", value=str(restrictions["exclusiveMinimum"]))
    if "exclusiveMaximum" in restrictions:
        ET.SubElement(element, f"{{{XSD_NAMESPACE}}}maxExclusive", value=str(restrictions["exclusiveMaximum"]))

# ####################################################################################################
# Esegue mapping dei tipi supportati da swagger/openapi a XSD
# ####################################################################################################
def map_supported_types(swagger_type, swagger_format=None):

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

# ####################################################################################################
# Esegue mapping dele string con restrizioni da swagger/openapi a XSD
# ####################################################################################################
def map_string_types_with_restrictions(restrictions):

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

# ####################################################################################################
# Esegue mapping degli intger con restrizioni da swagger/openapi a XSD
# ####################################################################################################
def map_integer_types_with_restrictions(swagger_type, swagger_format, restrictions):

    if swagger_type == "integer":
        min_ = restrictions.get("minimum")
        max_ = restrictions.get("maximum")

        if min_ == 0 and max_ == 2147483647:
            return "nonNegativeInteger"
        elif min_ == 1 and max_ == 2147483647:
            return "positiveInteger"

    return None  # fallback to manual restriction

# ####################################################################################################
# Risolve ricorsivamente gli $ref, evitando loop infiniti e unendo le proprietà
# ####################################################################################################       
def resolve_ref(schema, root_definitions, seen=None):

    if not isinstance(schema, dict):
        return schema

    if "$ref" in schema:
        ref = schema["$ref"]
        type_name = ref.split("/")[-1]
        
        if seen is None:
            seen = set()
            
        if type_name in seen:
            return {}  # evitiamo loop
        seen.add(type_name)

        resolved = root_definitions.get(type_name, {}).copy()
        nested = resolve_ref(resolved, root_definitions, seen)
        return {**nested, **schema}  # priorità a schema locale

    return schema
    
# ####################################################################################################
# Genera il file XSD
# ####################################################################################################
def generate_xsd(root_definitions,used_definitions,wadl_definitions):

    schema = ET.Element(f"{{{XSD_NAMESPACE}}}schema", attrib={
        "targetNamespace": TARGET_NAMESPACE,
        "elementFormDefault": "unqualified",
        f"xmlns:{TARGET_PREFIX}": TARGET_NAMESPACE
    })

    complex_types = []
    element_declarations = []
    string_restriction_registry = {}

    for idx, (def_name, def_body) in enumerate(root_definitions.items()):
        def_body = resolve_ref(def_body, root_definitions)
        complex_type = ET.Element(f"{{{XSD_NAMESPACE}}}complexType", name=def_name)
        
        sequence = ET.SubElement(complex_type, f"{{{XSD_NAMESPACE}}}sequence")
        required_fields = def_body.get("required", [])
        properties = def_body.get("properties", {})

        name_lengths = [len(p) for p, a in properties.items() if a.get("type") != "array"]
        max_name_len = max(name_lengths or [0])

        for prop_name, prop_attrs in properties.items():
            prop_attrs = resolve_ref(prop_attrs, root_definitions)
            swagger_type = prop_attrs.get("type")
            swagger_format = prop_attrs.get("format")
            restrictions = get_restrictions(prop_attrs)
            nullable = prop_attrs.get("nullable", False)

            if swagger_type == "array":
                items = prop_attrs.get("items", {})
                items = resolve_ref(items, root_definitions)

                item_type = items.get("type")
                item_format = items.get("format")
                item_restrictions = get_restrictions(items)
                item_nullable = items.get("nullable", False)

                wrapper_attrib = {"name": prop_name}
                if prop_name not in required_fields:
                    wrapper_attrib["minOccurs"] = "0"
                wrapper_el = ET.SubElement(sequence, f"{{{XSD_NAMESPACE}}}element", attrib=wrapper_attrib)

                complex_array = ET.SubElement(wrapper_el, f"{{{XSD_NAMESPACE}}}complexType")
                array_seq = ET.SubElement(complex_array, f"{{{XSD_NAMESPACE}}}sequence")
                item_el = ET.SubElement(array_seq, f"{{{XSD_NAMESPACE}}}element", attrib={
                    "name": "item", "minOccurs": "0", "maxOccurs": "unbounded"
                })

                if "$ref" in items:
                    ref_name = items["$ref"].split("/")[-1]
                    item_el.set("type", f"{TARGET_PREFIX}:{ref_name}")

                elif item_type:
                    simplified = map_integer_types_with_restrictions(item_type, item_format, item_restrictions)
                    if simplified:
                        item_el.set("type", f"{XSD_PREFIX}:{simplified}")
                    elif item_type == "string" and ("minLength" in item_restrictions or "maxLength" in item_restrictions):
                        type_name = map_string_types_with_restrictions(item_restrictions)
                        item_el.set("type", f"{TARGET_PREFIX}:{type_name}")
                        string_restriction_registry[type_name] = item_restrictions
                    elif item_restrictions:
                        base_type = map_supported_types(item_type, item_format)
                        if item_nullable:
                            union_type = ET.SubElement(item_el, f"{{{XSD_NAMESPACE}}}simpleType")
                            union = ET.SubElement(union_type, f"{{{XSD_NAMESPACE}}}union")
                            inline = ET.SubElement(union, f"{{{XSD_NAMESPACE}}}simpleType")
                            restriction = ET.SubElement(inline, f"{{{XSD_NAMESPACE}}}restriction", base=f"{XSD_PREFIX}:{base_type}")
                            map_restrictions(restriction, item_restrictions)
                            union.set("memberTypes", f"{TARGET_PREFIX}:emptyStringType")
                        else:
                            simple_type = ET.SubElement(item_el, f"{{{XSD_NAMESPACE}}}simpleType")
                            restriction = ET.SubElement(simple_type, f"{{{XSD_NAMESPACE}}}restriction", base=f"{XSD_PREFIX}:{base_type}")
                            map_restrictions(restriction, item_restrictions)
                    else:
                        item_el.set("type", f"{XSD_PREFIX}:{map_supported_types(item_type, item_format)}")
                        
            else:
                base_attrib = {"name": prop_name}
                simplified = map_integer_types_with_restrictions(swagger_type, swagger_format, restrictions)
                has_restrictions = bool(restrictions)
                base_type = None

                if simplified:
                    base_type = f"{XSD_PREFIX}:{simplified}"
                elif swagger_type == "string" and ("minLength" in restrictions or "maxLength" in restrictions):
                    type_name = map_string_types_with_restrictions(restrictions)
                    base_type = f"{TARGET_PREFIX}:{type_name}"
                    string_restriction_registry[type_name] = restrictions
                elif "$ref" in prop_attrs:
                    ref_name = prop_attrs["$ref"].split("/")[-1]
                    base_type = f"{TARGET_PREFIX}:{ref_name}"
                elif not has_restrictions:
                    base_type = f"{XSD_PREFIX}:{map_supported_types(swagger_type, swagger_format)}"

                if "name" in base_attrib:
                    padding = max_name_len - len(prop_name)
                    base_attrib["name"] = prop_name + (" " * padding)

                if base_type and not nullable:
                    base_attrib["type"] = base_type
                    el = ET.Element(f"{{{XSD_NAMESPACE}}}element", attrib=base_attrib)
                elif base_type and nullable:
                    el = ET.Element(f"{{{XSD_NAMESPACE}}}element", attrib={"name": base_attrib["name"]})
                    union_type = ET.SubElement(el, f"{{{XSD_NAMESPACE}}}simpleType")
                    union = ET.SubElement(union_type, f"{{{XSD_NAMESPACE}}}union", memberTypes=f"{base_type} {TARGET_PREFIX}:emptyStringType")
                elif has_restrictions:
                    el = ET.Element(f"{{{XSD_NAMESPACE}}}element", attrib={"name": base_attrib["name"]})
                    if nullable:
                        union_type = ET.SubElement(el, f"{{{XSD_NAMESPACE}}}simpleType")
                        union = ET.SubElement(union_type, f"{{{XSD_NAMESPACE}}}union")
                        inline = ET.SubElement(union, f"{{{XSD_NAMESPACE}}}simpleType")
                        restriction = ET.SubElement(inline, f"{{{XSD_NAMESPACE}}}restriction", base=f"{XSD_PREFIX}:{map_supported_types(swagger_type, swagger_format)}")
                        map_restrictions(restriction, restrictions)
                        union.set("memberTypes", f"{TARGET_PREFIX}:emptyStringType")
                    else:
                        simple_type = ET.SubElement(el, f"{{{XSD_NAMESPACE}}}simpleType")
                        restriction = ET.SubElement(simple_type, f"{{{XSD_NAMESPACE}}}restriction", base=f"{XSD_PREFIX}:{map_supported_types(swagger_type, swagger_format)}")
                        map_restrictions(restriction, restrictions)
                else:
                    continue

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

    # ================================================================================================
    # Genera special type for nullability
    # ================================================================================================
    schema.append(ET.Comment("#" * 100))
    schema.append(ET.Comment(" EmptyStringType "))
    schema.append(ET.Comment("#" * 100))

    empty_string_type = ET.Element(f"{{{XSD_NAMESPACE}}}simpleType", name="emptyStringType")
    restr = ET.SubElement(empty_string_type, f"{{{XSD_NAMESPACE}}}restriction", base=f"{XSD_PREFIX}:string")
    ET.SubElement(restr, f"{{{XSD_NAMESPACE}}}length", value="0")
    schema.append(empty_string_type)

    # ================================================================================================
    # Genera SimpleTypes
    # ================================================================================================
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
        restriction = ET.SubElement(simple_type, f"{{{XSD_NAMESPACE}}}restriction", base=f"{XSD_PREFIX}:string")
        map_restrictions(restriction, restrictions)
        schema.append(simple_type)

    # ================================================================================================
    # Genera ComplexTypes
    # ================================================================================================
    schema.append(ET.Comment("#" * 100))
    schema.append(ET.Comment(" ComplexTypes "))
    schema.append(ET.Comment("#" * 100))

    for ct in complex_types:
        schema.append(ct)

    # ================================================================================================
    # Genera Element
    # ================================================================================================
    schema.append(ET.Comment("#" * 100))
    schema.append(ET.Comment(" Elements "))
    schema.append(ET.Comment("#" * 100))

    for def_name in element_declarations:
        ET.SubElement(schema, f"{{{XSD_NAMESPACE}}}element", attrib={
            "name": def_name,
            "type": f"{TARGET_PREFIX}:{def_name}"
        })

    # ================================================================================================

    return schema

# ####################################################################################################
# Genera il file WADL
# ####################################################################################################
def generate_wadl(spec,version,root_definitions,wadl_definitions,xsd_filename):
    
    application = ET.Element(f"{{{WADL_NAMESPACE}}}application", attrib={
        f"xmlns:{XSD_PREFIX}": XSD_NAMESPACE,
        f"xmlns:{TARGET_PREFIX}": TARGET_NAMESPACE
    })
    
    # ================================================================================================
    # Genera Grammars
    # ================================================================================================
    application.append(ET.Comment("#" * 100))
    application.append(ET.Comment(" Grammars "))
    application.append(ET.Comment("#" * 100))    
    gram = ET.SubElement(application,f"{{{WADL_NAMESPACE}}}grammars")
    ET.SubElement(gram,f"{{{WADL_NAMESPACE}}}include", href=os.path.basename(xsd_filename))

    # ================================================================================================
    # Genera Resources
    # ================================================================================================
    application.append(ET.Comment("#" * 100))
    application.append(ET.Comment(" Resources "))
    application.append(ET.Comment("#" * 100))
    resources = ET.SubElement(application,f"{{{WADL_NAMESPACE}}}resources", base=spec.get("servers", [{}])[0].get("url", "/") if version == "openapi3" else "")

    # ================================================================================================
    # Genera Resource
    # ================================================================================================

    for idx, (path, methods) in enumerate(spec.get("paths", {}).items()):
        
        if idx > 0:
           resources.append(ET.Comment(" ~~~~~~~~ "))
                
        resource = ET.SubElement(resources,f"{{{WADL_NAMESPACE}}}resource", path=path)

        # ------------------------------------------------------------------------------------------------
        # Genera Method
        # ------------------------------------------------------------------------------------------------
        
        for method_name, method_def in methods.items():
        
            operationId = method_def.get("operationId","")
            if operationId=="":
                method = ET.SubElement(resource,f"{{{WADL_NAMESPACE}}}method", name=method_name.upper())
            else:
                method = ET.SubElement(resource,f"{{{WADL_NAMESPACE}}}method", name=method_name.upper(),id=operationId)            
                        
            # ------------------------------------------------------------------------------------------------
            # Genera Request
            # ------------------------------------------------------------------------------------------------

            request = ET.SubElement(method,f"{{{WADL_NAMESPACE}}}request")

            # Genera representation per i request body dell'openapi3
            if (version == "openapi3") and ("requestBody" in method_def):
                content = method_def["requestBody"].get("content", {})
                for mt, body_def in content.items():
                    schema_ref = body_def.get("schema", {}).get("$ref")
                    if schema_ref:
                        type_name = schema_ref.split("/")[-1]
                        wadl_definitions.add(type_name)
                        ET.SubElement(request,f"{{{WADL_NAMESPACE}}}representation", mediaType=mt, element=f"{TARGET_PREFIX}:{type_name}")                        

            # Genera parameters ed eventuali representation per i request body del swagger2, mappando i style da swagger/openapi3 a WADL
            consumes = method_def.get("consumes", [])
            parameters = method_def.get("parameters", [])

            for param in parameters:
                param_name = param["name"]
                param_in = param.get("in", "query")
                
                if param_in == "path":
                    param_style = "template"
                elif param_in in ["query", "header", "matrix"]:
                    param_style = param_in
                elif version == "swagger2" and param_in=="body" and "$ref" in param.get("schema", {}):
                    type_name = param["schema"]["$ref"].split("/")[-1]
                    for mt in consumes:
                        wadl_definitions.add(type_name)
                        ET.SubElement(request,f"{{{WADL_NAMESPACE}}}representation", mediaType=mt, element=f"{TARGET_PREFIX}:{type_name}")
                    continue
                else:
                    continue  # Unsupported param location

                param_type = map_supported_types(param.get("type", "string"), param.get("format"))
                ET.SubElement(request,f"{{{WADL_NAMESPACE}}}param", name=param_name, style=param_style, type=f"{XSD_PREFIX}:{param_type}", required=str(param.get("required", False)).lower())

            # ------------------------------------------------------------------------------------------------
            # Gestisce Responses
            # ------------------------------------------------------------------------------------------------

            responses = method_def.get("responses", {})
            
            for status, response in responses.items():
                response_el = ET.SubElement(method,f"{{{WADL_NAMESPACE}}}response", status=status)
                contents = response.get("content", {}) if version == "openapi3" else {"application/json": response}
                for mt, content_def in contents.items():
                    schema = content_def.get("schema", {})
                    if "$ref" in schema:
                        type_name = schema["$ref"].split("/")[-1]
                        wadl_definitions.add(type_name)
                        ET.SubElement(response_el,f"{{{WADL_NAMESPACE}}}representation", mediaType=mt, element=f"{TARGET_PREFIX}:{type_name}")
                    else:
                        ET.SubElement(response_el,f"{{{WADL_NAMESPACE}}}representation", mediaType=mt)

    # ================================================================================================

    return application

# ####################################################################################################
# Main function
# ####################################################################################################
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
    
    # Censisce i tipi utilizzati a vario titolo
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

# ####################################################################################################
# Entry point
# ####################################################################################################
if __name__ == "__main__":
    main()
