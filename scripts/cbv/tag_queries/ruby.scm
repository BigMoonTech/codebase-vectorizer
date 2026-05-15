(class) @definition.class
(module) @definition.module
(method) @definition.function
(singleton_method) @definition.method
(assignment) @definition.variable

(superclass (constant) @reference.inherits)
(call) @reference.call
(assignment right: (identifier) @reference.identifier)
(call arguments: (argument_list (identifier) @reference.identifier))
((call method: (identifier) @reference.identifier) @reference.import
 (#eq? @reference.identifier "require"))
