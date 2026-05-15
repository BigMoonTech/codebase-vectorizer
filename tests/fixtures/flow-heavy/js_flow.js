export function decideJs(user, amount) {
  let approved = false;
  if (user.isAdmin) {
    approved = true;
  } else {
    for (const item of user.items) {
      if (item.blocked) {
        return false;
      }
      approved = amount < 100;
    }
  }
  return approved;
}
