(class_declaration) @definition.class
(interface_declaration) @definition.class
(function_declaration) @definition.function
(generator_function_declaration) @definition.function
(method_definition) @definition.method
(method_signature) @definition.method
(abstract_method_signature) @definition.method
(function_signature) @definition.function
(function_expression) @definition.function
(generator_function) @definition.function
(arrow_function) @definition.function
(public_field_definition) @definition.variable
(variable_declarator) @definition.variable

(import_statement) @reference.import
(extends_clause (identifier) @reference.inherits)
(implements_clause (type_identifier) @reference.inherits)
(call_expression) @reference.call
(public_field_definition value: (identifier) @reference.identifier)
(public_field_definition value: (member_expression object: (identifier) @reference.identifier))
(variable_declarator value: (identifier) @reference.identifier)
(variable_declarator value: (member_expression object: (identifier) @reference.identifier))
(call_expression arguments: (arguments (identifier) @reference.identifier))
