(class_declaration) @definition.class
(interface_declaration) @definition.class
(enum_declaration) @definition.class
(record_declaration) @definition.class
(struct_declaration) @definition.class
(method_declaration) @definition.method
(constructor_declaration) @definition.method
(local_function_statement) @definition.method
(variable_declarator) @definition.variable

(using_directive) @reference.import
(base_list (identifier) @reference.inherits)
(invocation_expression) @reference.call
(variable_declarator name: (identifier) "=" (identifier) @reference.identifier)
(invocation_expression arguments: (argument_list (argument (identifier) @reference.identifier)))
