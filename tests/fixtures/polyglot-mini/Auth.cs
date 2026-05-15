using System;

class Base {}
interface ILogin {}

class Auth : Base, ILogin
{
    int token = seed;

    void Login()
    {
        Check(token);
    }
}
