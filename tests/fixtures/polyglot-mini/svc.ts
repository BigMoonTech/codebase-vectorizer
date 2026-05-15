interface User {
    name: string;
}

class UserService extends BaseService implements User {
    field = currentUser;

    login(): void {
        const token = fetchUser(field);
    }
}

function loadUser(): User {
    return fetchUser();
}
