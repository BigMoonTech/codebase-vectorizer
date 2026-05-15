import { snakeCase } from './fmt.js';

class Formatter extends BaseFormatter {
    format(input) {
        const token = currentUser;
        return snakeCase(token);
    }
}

export function camelCase(x) {
    return snakeCase(x);
}
