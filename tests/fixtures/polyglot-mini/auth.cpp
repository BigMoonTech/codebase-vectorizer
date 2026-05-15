#include <vector>

class Base {};

class Auth : public Base {
    int token;

    void login()
    {
        check(token);
    }
};

int login()
{
    return check();
}
