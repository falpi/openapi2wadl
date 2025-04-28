#!/usr/bin/env python3
# openapi2wadl.py
# Converts Swagger 2.0 or OpenAPI 3.0 into WADL + XSD

# ####################################################################################################
# Referenze
# ####################################################################################################

import os
import re
import sys
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

    # Sposta in fondo minOccurs, maxOccurs, nillable sugli "element"
    fixed = re.sub(r'<(.+?)(?=\snillable)(\snillable="[^"]*")([^\/|>]*)(\/)?>', r'<\1\3\2\4>', fixed)
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
# Risolve ricorsivamente gli $ref, evitando loop infiniti e unendo le proprietà
# ####################################################################################################       
def resolve_ref(schema, root_definitions, seen=None):

    # se è un $ref esegue
    if "$ref" in schema:
    
        # determina il tipo referenziato
        type_name = schema.get("$ref").split("/")[-1]
        
        # se il controllo dei loop non è inizializzato provvede, altrimenti se il tipo è già stato visitato esce per evitare i loop
        if seen is None:
            seen = set()           
        elif type_name in seen:
            return {}  
            
        # aggiunge il tipo al controllo dei loop
        seen.add(type_name)

        # determina ricorsivamente il primo schema della catena nidificata di $ref
        resolved = root_definitions.get(type_name, {}).copy()        
        nested = resolve_ref(resolved, root_definitions, seen)
        
        # restituisce 
        return {**nested, **schema}  # priorità a schema locale

    # restisuisce immodificato lo schema in ingresso
    return schema

# ####################################################################################################
# Acquisce le restrizioni dalle proprietà dal swagger/openapi
# ####################################################################################################
def get_restrictions(schema):
    return {
        k: schema[k]
        for k in ["minLength", "maxLength", "pattern", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"] if k in schema
    }
    
# ####################################################################################################
# Esegue mapping delle restrizioni da swagger/openapi a XSD
# ####################################################################################################
def map_restrictions(element, schema):

    if "pattern" in schema:
        ET.SubElement(element, f"{{{XSD_NAMESPACE}}}pattern", value=schema["pattern"])
        
    if "minLength" in schema:
        ET.SubElement(element, f"{{{XSD_NAMESPACE}}}minLength", value=str(schema["minLength"]))
        
    if "maxLength" in schema:
        ET.SubElement(element, f"{{{XSD_NAMESPACE}}}maxLength", value=str(schema["maxLength"]))
        
    if "minimum" in schema:
        if schema.get("exclusiveMinimum",False):
            ET.SubElement(element, f"{{{XSD_NAMESPACE}}}minExclusive", value=str(schema["minimum"]))
        else:
            ET.SubElement(element, f"{{{XSD_NAMESPACE}}}minInclusive", value=str(schema["minimum"]))

    if "maximum" in schema:
        if schema.get("exclusiveMaximum",False):
            ET.SubElement(element, f"{{{XSD_NAMESPACE}}}maxExclusive", value=str(schema["maximum"]))
        else:
            ET.SubElement(element, f"{{{XSD_NAMESPACE}}}maxInclusive", value=str(schema["maximum"]))

# ####################################################################################################
# Gestisce mapping della nullability dei tipi atomici
# ####################################################################################################
def map_nullability(schema, type_prefix, type_name, nullability_registry, restriction_registry):
   
    if not schema.get("nullable",False):
        return f"{type_prefix}:{type_name}"
    else:        
        nillable_type = f"{type_name}Nillable"
    
        if not nillable_type in nullability_registry:
           simple_type = ET.Element(f"{{{XSD_NAMESPACE}}}simpleType", name=nillable_type)
           union = ET.SubElement(simple_type, f"{{{XSD_NAMESPACE}}}union", memberTypes=f"{type_prefix}:{type_name} {TARGET_PREFIX}:emptyString")
           nullability_registry[nillable_type] = simple_type

        schema.pop("nullable")
        
        return f"{TARGET_PREFIX}:{nillable_type}"

# ####################################################################################################
# Esegue mapping dei tipi swagger/openapi a XSD
# ####################################################################################################
def map_xsd_types(schema, nullability_registry, restriction_registry):
        
    # acquisisce gli attributi del tipo
    type_prefix = XSD_PREFIX
    type_name = schema.get("type","")
    type_format = schema.get("format","")
    type_nullable = schema.get("nullable",False)
    type_restrictions = get_restrictions(schema)
        
    # gestisce tipi boolean
    if type_name == "boolean":
        return map_nullability(schema,type_prefix,type_name,nullability_registry,restriction_registry)
                                    
    # gestisce tipi byte
    if type_name == "string" and type_format == "byte":
        return map_nullability(schema,type_prefix,"base64Binary",nullability_registry,restriction_registry)

    # gestisce fomati data stringa
    if type_name == "string" and type_format in ["date", "date-time"]:
        return map_nullability(schema,type_prefix,"dateTime" if type_format == "date-time" else "date",nullability_registry,restriction_registry)

    # gestisce tipi stringa
    if type_name == "string":
    
        # acquisisce eventuali restrizioni sui limiti
        min_len = type_restrictions.get("minLength", 0)
        max_len = type_restrictions.get("maxLength", "")

        # costruisce nome tipo riusabile
        pre_part = "emptyString" if max_len==0 else "openString" if not isinstance(max_len, int) else "string"       
        min_part = f"{min_len}" if isinstance(min_len, int) and min_len>1 else ""
        max_part = f"{max_len}" if isinstance(max_len, int) and max_len>0 else ""
        sep_part = "to" if min_part!="" and max_part!="" else ""  
        end_part = "Nillable" if min_len==0 else ""        
        type_name = pre_part+min_part+sep_part+max_part+end_part
                        
        # se non è già definito predispone simple type XML del tipo riusabile
        if not type_name in restriction_registry:
            simple_type = ET.Element(f"{{{XSD_NAMESPACE}}}simpleType", name=type_name)
            restriction = ET.SubElement(simple_type, f"{{{XSD_NAMESPACE}}}restriction", base=f"{XSD_PREFIX}:string")
            map_restrictions(restriction, dict(filter(lambda item: item[0] in {"minLength","maxLength"}, type_restrictions.items())))        
            restriction_registry[type_name] = simple_type        

        # rimuove dallo schema le restrizioni mappate sul tipo riusabile (che non è necessario rigestire nel rendering dell'elemento)
        schema.pop("minLength",None)
        schema.pop("maxLength",None)

        return f"{TARGET_PREFIX}:{type_name}"

    # gestisce tipi numerici
    if (((type_name == "number") and (type_format in ["","float","double"])) or
        ((type_name == "integer") and (type_format in ["","int32","int64"]))):  
    
        # corregge tipo in base all'eventuale specificatore di formato
        if (type_name=="number"):
            type_name = "decimal" if type_format == "" else type_format
        else:        
            type_name = "integer" if type_format == "" else "int" if type_format == "int32" else "long"  
        
        # acquisisce eventuali restrizioni sui limiti
        min_val = type_restrictions.get("minimum","")
        max_val = type_restrictions.get("maximum","")
        min_excl = type_restrictions.get("exclusiveMinimum",False)
        max_excl = type_restrictions.get("exclusiveMaximum",False)
                   
        # se ci sono restrizioni ridondanti sui limiti superiori le rimuove per semplificare la eventuale definizione dei tipi riusabili
        if (((type_name=="int") and 
             (((max_val == 2147483648) and (max_excl==True)) or
              ((max_val == 2147483647) and (max_excl==False)))) or
            ((type_name=="long") and 
             (((max_val == 9223372036854775808) and (max_excl==True)) or
              ((max_val == 9223372036854775807) and (max_excl==False))))):
             
            max_val = ""
            type_restrictions.pop("maximum",None)
            type_restrictions.pop("exclusiveMaximum",None)
                                          
        # se ci sono restrizioni sui limiti introduce tipo riusabile
        if (min_val!="") or (max_val!=""):

            # imposta il prefix dei tipi riusabili e salva il nome del tipo atomico
            type_prefix = TARGET_PREFIX            
            atomic_name = type_name
        
            # costruisce nome tipo riusabile
            min_part = ("Gt"+("" if min_excl else "e")+f"{min_val}") if isinstance(min_val, int) else ""
            max_part = ("Lt"+("" if max_excl else "e")+f"{max_val}") if isinstance(max_val, int) else ""          
            end_part = min_part+max_part          
            
            # ridenomina alcuni tipi
            if end_part == "Gt0":
                type_name = "positive"+type_name.capitalize()
            elif end_part == "Gte0":
                type_name = "nonNegative"+type_name.capitalize()
            elif end_part == "Lt0":
                type_name = "negative"+type_name.capitalize()
            elif end_part == "Lte0":
                type_name = "nonPositive"+type_name.capitalize()
            else:
                type_name = type_name+end_part
                
            # se non è già definito predispone simple type XML del tipo riusabile
            if not type_name in restriction_registry:            
                simple_type = ET.Element(f"{{{XSD_NAMESPACE}}}simpleType", name=type_name)
                restriction = ET.SubElement(simple_type, f"{{{XSD_NAMESPACE}}}restriction", base=f"{XSD_PREFIX}:{atomic_name}")
                map_restrictions(restriction, dict(filter(lambda item: item[0] in {"minimum","maximum","exclusiveMinimum","exclusiveMaximum"}, type_restrictions.items())))            
                restriction_registry[type_name] = simple_type
                       
            # rimuove dallo schema le restrizioni mappate sul tipo riusabile (che non è necessario rigestire nel rendering dell'elemento)
            schema.pop("minimum",None)
            schema.pop("maximum",None)
            schema.pop("exclusiveMinimum",None)
            schema.pop("exclusiveMaximum",None)

        return map_nullability(schema,type_prefix,type_name,nullability_registry,restriction_registry)
            
    # genera eccezione    
    print("Unsupported type: ",schema)
    sys.exit()
    
# ####################################################################################################
# Genera Element/SimpleType
# ####################################################################################################    
def generate_xsd_simple_type(level, parent_element, schema, nullability_registry, restriction_registry):

    # se si tratta di un ref lo gestisce ad hoc
    if "$ref" in schema:
        ref_name = schema["$ref"].split("/")[-1]
        parent_element.set('type',f"{TARGET_PREFIX}:{ref_name}")
        return

    # se necessario aggiunge attributo di nullability
    if schema.get("nullable", False):
       parent_element.set('nillable',"true")    
            
    # determina il tipo xsd più appropriato 
    mapped_type = map_xsd_types(schema,nullability_registry,restriction_registry)

    # riacquisisce parametri tipo 
    type_nullable = schema.get("nullable", False)    
    type_restrictions = get_restrictions(schema)
    
    # crea il nodo xml appropriato al tipo dell'elemento
    if not type_restrictions:
    
        if not type_nullable:
            parent_element.set('type',mapped_type)
        else:
            simple_type = ET.SubElement(parent_element, f"{{{XSD_NAMESPACE}}}simpleType")
            union = ET.SubElement(simple_type, f"{{{XSD_NAMESPACE}}}union", memberTypes=f"{mapped_type} {TARGET_PREFIX}:emptyString")    
    
    elif not type_nullable:
        simple_type = ET.SubElement(parent_element, f"{{{XSD_NAMESPACE}}}simpleType")
        restriction = ET.SubElement(simple_type, f"{{{XSD_NAMESPACE}}}restriction", base=mapped_type)
        map_restrictions(restriction, type_restrictions)
    else:
        simple_type = ET.SubElement(parent_element, f"{{{XSD_NAMESPACE}}}simpleType")
        union = ET.SubElement(simple_type, f"{{{XSD_NAMESPACE}}}union", memberTypes=f"{TARGET_PREFIX}:emptyString")            
        inline = ET.SubElement(union, f"{{{XSD_NAMESPACE}}}simpleType")
        restriction = ET.SubElement(inline, f"{{{XSD_NAMESPACE}}}restriction", base=mapped_type)
        map_restrictions(restriction, type_restrictions)

# ####################################################################################################
# Genera ComplexType
# ####################################################################################################
def generate_xsd_type(level, parent_element, root_name, def_body, root_definitions, nullability_registry, restriction_registry):

    # verifica se si tratta di un $ref
    def_ref = def_body.get("$ref","");                    
                    
    # risolve eventuali $ref sullo schema body
    def_body = resolve_ref(def_body, root_definitions)      

    #  determina il tipo dello schema
    def_type = def_body.get("type", "");    
    
    # se si tratta di un array esegue
    if def_ref=="" and def_type == "array":
                
        # crea nodi per array
        array_type = ET.SubElement(parent_element,f"{{{XSD_NAMESPACE}}}complexType")             
        array_sequence = ET.SubElement(array_type, f"{{{XSD_NAMESPACE}}}sequence")
        array_element = ET.SubElement(array_sequence, f"{{{XSD_NAMESPACE}}}element", attrib={
            "name": "item", "minOccurs": "0", "maxOccurs": "unbounded"
        })
        
        # se è un nodo radice aggiunge l'attributo del nome
        if (root_name!=""):
           array_type.set("name",root_name)
        
        # genera definizione del tipo in modo ricorsivo
        generate_xsd_type(level+1,array_element,"",def_body.get("items", {}),root_definitions,nullability_registry,restriction_registry)               
    
    # se si tratta di un object esegue
    elif def_ref=="" and def_type == "object":
                         
        # determina attributi accessori dell'object    
        def_required = def_body.get("required", [])
        def_properties = def_body.get("properties", {})

        # determina padding per i type degli elementi
        name_padding = max([len(p) for p, a in def_properties.items() if a.get("type") != "array"] or [0])
           
        # crea nodi per complex type
        complex_type = ET.SubElement(parent_element,f"{{{XSD_NAMESPACE}}}complexType")             
        sequence = ET.SubElement(complex_type, f"{{{XSD_NAMESPACE}}}sequence")

        # se è un nodo radice aggiunge l'attributo del nome
        if (root_name!=""):
           complex_type.set("name",root_name)

        # esegue un ciclo su tutte le proprietà del complex type
        for prop_name, prop_attrs in def_properties.items():
                        
            # crea attributi per nodo 
            element_attrib = {"name": prop_name}
            
            if prop_name not in def_required:
                element_attrib["minOccurs"] = "0"

            # verifica se si tratta di un $ref
            prop_ref = prop_attrs.get("$ref","");                    
                
            # se si tratta di un tipo array o object esegue, altrimenti procede
            if prop_ref=="" and prop_attrs.get("type") in ["array","object"]:
                                                    
                # crea nodo per elemento di tipo array
                complex_element = ET.SubElement(sequence,f"{{{XSD_NAMESPACE}}}element", attrib=element_attrib)
                
                # genera definizione del tipo
                generate_xsd_type(level+1,complex_element,"",prop_attrs,root_definitions,nullability_registry,restriction_registry)
                
            else:
            
                # corregge nome elemento per introdurre padding
                element_attrib["name"] = element_attrib["name"] + (" " * (name_padding-len(prop_name)))
                    
                # crea nodo per elemento semplice
                simple_element = ET.SubElement(sequence,f"{{{XSD_NAMESPACE}}}element", attrib=element_attrib)
                
                # genera definizione del tipo
                generate_xsd_simple_type(level,simple_element,prop_attrs,nullability_registry,restriction_registry)                                

    else:

        # genera definizione del tipo
        generate_xsd_simple_type(level,parent_element,def_body,nullability_registry,restriction_registry)  

# ####################################################################################################
# Genera il file XSD
# ####################################################################################################
def generate_xsd(root_definitions,used_definitions,wadl_definitions,nullability_registry,restriction_registry):

    # funzione di supporto per ordinamento dei simple type
    def sorting_criteria(restriction_element):
    
        min_len = None
        max_len = None
        type_order = None
        
        for child in restriction_element.iter():
            if child.tag.endswith("restriction"):
                type_order = child.attrib.get("base")
            if child.tag.endswith("minLength"):
                min_len = int(child.attrib.get("value", "0"))
            if child.tag.endswith("maxLength"):
                max_len = int(child.attrib.get("value", str(float('inf'))))
                
        return (type_order, max_len or float('inf'), min_len or 0)

    # prepara variabili di lavoro
    complex_types = ET.Element("root")
    element_declarations = []

    # genera nodo radice dell'XSD
    schema = ET.Element(f"{{{XSD_NAMESPACE}}}schema", attrib={
        "targetNamespace": TARGET_NAMESPACE,
        "elementFormDefault": "unqualified",
        f"xmlns:{TARGET_PREFIX}": TARGET_NAMESPACE
    })

    # ================================================================================================
    # Prepara tipi
    # ================================================================================================

    # Esegue un ciclo su tutti i tipi definiti al primo livello del contract
    for idx, (def_name, def_body) in enumerate(root_definitions.items()):

        # se necessario crea separatore tra i complex type
        if not def_name in used_definitions:
            complex_types.append(ET.Comment(f" #unused# "))
        elif idx > 0:
            complex_types.append(ET.Comment(" ~~~~~~~~ "))

        # genera il prossimo complex type
        generate_xsd_type(0,complex_types, def_name, def_body, root_definitions, nullability_registry, restriction_registry)
                            
        # se il complex type è referenziato dal wadl 
        if def_name in wadl_definitions:
            element_declarations.append(def_name)

    # ================================================================================================
    # Genera Special Type 
    # ================================================================================================
    schema.append(ET.Comment("#" * 100))
    schema.append(ET.Comment(" Special types for nullability of atomic types"))
    schema.append(ET.Comment("#" * 100))

    empty_string = ET.Element(f"{{{XSD_NAMESPACE}}}simpleType", name="emptyString")
    restriction = ET.SubElement(empty_string, f"{{{XSD_NAMESPACE}}}restriction", base=f"{XSD_PREFIX}:string")
    ET.SubElement(restriction, f"{{{XSD_NAMESPACE}}}length", value="0")
    schema.append(empty_string)
    
    for element in nullability_registry.values():    
        schema.append(ET.Comment(" ~~~~~~~~ "))
        schema.append(element)

    # ================================================================================================
    # Genera Reusable Types
    # ================================================================================================
    schema.append(ET.Comment("#" * 100))
    schema.append(ET.Comment(" Reusable types "))
    schema.append(ET.Comment("#" * 100))

    sorted_simpletypes = sorted(
        restriction_registry.items(),
        key=lambda item: (
            sorting_criteria(item[1])[0], 
            sorting_criteria(item[1])[1],
            sorting_criteria(item[1])[2]
            #item[0].lower()[0]
        )
    )
    
    for idx, (type_name, restriction) in enumerate(sorted_simpletypes):
    
        if idx > 0:
            schema.append(ET.Comment(" ~~~~~~~~ "))
            
        schema.append(restriction)

    # ================================================================================================
    # Genera Complex Types
    # ================================================================================================
    schema.append(ET.Comment("#" * 100))
    schema.append(ET.Comment(" Complex types "))
    schema.append(ET.Comment("#" * 100))

    for child in complex_types:
       schema.append(child);

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
def generate_wadl(spec,version,root_definitions,wadl_definitions,xsd_filename,nullability_registry,restriction_registry):
    
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
                param_schema = param.get("schema",{})
                param_in = param.get("in", "query")
                
                if param_in == "path":
                    param_style = "template"
                elif param_in in ["query", "header", "matrix"]:
                    param_style = param_in
                elif version == "swagger2" and param_in=="body" and "$ref" in param_schema:
                    type_name = param_schema["$ref"].split("/")[-1]
                    for mt in consumes:
                        wadl_definitions.add(type_name)
                        ET.SubElement(request,f"{{{WADL_NAMESPACE}}}representation", mediaType=mt, element=f"{TARGET_PREFIX}:{type_name}")
                    continue
                else:
                    continue  # Unsupported param location

                param_type = map_xsd_types(param_schema,nullability_registry,restriction_registry)
                ET.SubElement(request,f"{{{WADL_NAMESPACE}}}param", name=param_name, style=param_style, type=param_type, required=str(param.get("required", False)).lower())

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
    nullability_registry = {}
    restriction_registry = {}

    wadl_definitions = set()
    root_definitions = extract_root_definitions(spec, version)
    used_definitions = extract_used_definitions(spec, version, root_definitions)
    
    # Generazione del WADL
    wadl_tree = generate_wadl(spec,version,root_definitions,wadl_definitions,xsd_filename,nullability_registry,restriction_registry)

    # Generazione XSD 
    xsd_tree = generate_xsd(root_definitions,used_definitions,wadl_definitions,nullability_registry,restriction_registry)

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
