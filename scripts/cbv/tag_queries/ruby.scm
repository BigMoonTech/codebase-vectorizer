(class) @definition.class
(module) @definition.module
(method) @definition.function
(singleton_method) @definition.method

(call) @reference.call
((call method: (identifier) @reference.identifier) @reference.import
 (#eq? @reference.identifier "require"))
