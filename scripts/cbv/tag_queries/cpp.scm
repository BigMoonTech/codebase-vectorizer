(class_specifier) @definition.class
(struct_specifier) @definition.class
(field_declaration) @definition.variable
(function_definition) @definition.function

(preproc_include) @reference.import
(class_specifier (base_class_clause (type_identifier) @reference.inherits))
(struct_specifier (base_class_clause (type_identifier) @reference.inherits))
(call_expression) @reference.call
(call_expression arguments: (argument_list (identifier) @reference.identifier))
