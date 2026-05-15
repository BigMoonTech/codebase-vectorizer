import os


class Base:
    pass


class Auth(Base):
    token = os.getenv("TOKEN")

    def login(self):
        user = current_user
        return check(user)
