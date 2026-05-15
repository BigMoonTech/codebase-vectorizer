(class_declaration) @definition.class
(interface_declaration) @definition.class
(enum_declaration) @definition.class
(record_declaration) @definition.class
(method_declaration) @definition.method
(constructor_declaration) @definition.method
(variable_declarator) @definition.variable

(import_declaration) @reference.import
(class_declaration (superclass (type_identifier) @reference.inherits))
(class_declaration (super_interfaces (type_list (type_identifier) @reference.inherits)))
(method_invocation) @reference.call
(variable_declarator value: (identifier) @reference.identifier)
(method_invocation arguments: (argument_list (identifier) @reference.identifier))
