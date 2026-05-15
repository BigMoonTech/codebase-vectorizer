(function_declaration) @definition.function
(method_declaration) @definition.method
(type_spec) @definition.class
(var_spec) @definition.variable
(short_var_declaration) @definition.variable

(import_declaration) @reference.import
(call_expression) @reference.call
(var_spec (identifier) "=" (expression_list (identifier) @reference.identifier))
(short_var_declaration (expression_list (identifier)) ":=" (expression_list (identifier) @reference.identifier))
(call_expression arguments: (argument_list (identifier) @reference.identifier))
