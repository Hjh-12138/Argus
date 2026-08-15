def search(db, user_input):
    return db.execute("SELECT * FROM users WHERE name = %s", (user_input,))
