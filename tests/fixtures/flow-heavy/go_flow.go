package flowheavy

type User struct {
	IsAdmin bool
	Items   []Item
}

type Item struct {
	Blocked bool
}

func DecideGo(user User, amount int) bool {
	approved := false
	if user.IsAdmin {
		approved = true
	} else {
		for _, item := range user.Items {
			if item.Blocked {
				return false
			}
			approved = amount < 100
		}
	}
	return approved
}
