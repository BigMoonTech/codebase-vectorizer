def decide(user, amount):
    approved = False
    if user.is_admin:
        approved = True
    elif amount < 100:
        approved = True
    return approved
