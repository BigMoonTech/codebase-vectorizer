export function decideTs(user: { isAdmin: boolean; items: Array<{ blocked: boolean }> }, amount: number): boolean {
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
