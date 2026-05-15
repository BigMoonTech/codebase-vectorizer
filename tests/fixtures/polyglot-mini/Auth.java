import java.util.List;

class Base {}
interface Login {}

class Auth extends Base implements Login {
    int token = seed;

    void login() {
        check(token);
    }
}
