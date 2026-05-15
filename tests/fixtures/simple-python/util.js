// Small JS file to exercise the AST chunker on a non-Python file.
export function camelCase(s) {
    return s.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
}

export function snakeCase(s) {
    return s.replace(/([a-z])([A-Z])/g, "$1_$2").toLowerCase();
}
