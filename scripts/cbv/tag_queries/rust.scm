(struct_item) @definition.class
(enum_item) @definition.class
(trait_item) @definition.class
(function_item) @definition.function
(let_declaration) @definition.variable

(use_declaration) @reference.import
(call_expression) @reference.call
(call_expression arguments: (arguments (identifier) @reference.identifier))
