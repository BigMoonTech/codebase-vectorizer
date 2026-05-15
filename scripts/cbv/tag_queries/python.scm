(class_definition) @definition.class
(function_definition) @definition.function
(assignment) @definition.variable

(import_statement) @reference.import
(import_from_statement) @reference.import
(class_definition (argument_list (identifier) @reference.inherits))
(call) @reference.call
(assignment right: (identifier) @reference.identifier)
(call arguments: (argument_list (identifier) @reference.identifier))
