(class_declaration) @definition.class
(function_declaration) @definition.function
(generator_function_declaration) @definition.function
(method_definition) @definition.method
(function_expression) @definition.function
(generator_function) @definition.function
(arrow_function) @definition.function
(variable_declarator) @definition.variable

(import_statement) @reference.import
(class_declaration (class_heritage (identifier) @reference.inherits))
(call_expression) @reference.call
(variable_declarator value: (identifier) @reference.identifier)
(variable_declarator value: (member_expression object: (identifier) @reference.identifier))
(call_expression arguments: (arguments (identifier) @reference.identifier))
