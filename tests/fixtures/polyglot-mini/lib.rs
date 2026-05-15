use crate::auth;

struct User;

impl User {
    fn login(&self) {
        auth::check();
    }
}
