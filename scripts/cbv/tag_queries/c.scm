(struct_specifier) @definition.class
(function_definition) @definition.function
(init_declarator) @definition.variable

(preproc_include) @reference.import
(call_expression) @reference.call
(init_declarator value: (identifier) @reference.identifier)
(call_expression arguments: (argument_list (identifier) @reference.identifier))
