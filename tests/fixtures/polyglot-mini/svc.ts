interface User {
    name: string;
}

function loadUser(): User {
    return fetchUser();
}
