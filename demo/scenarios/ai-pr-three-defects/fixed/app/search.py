def search(db, user_input):
    query = "SELECT * FROM users WHERE name = %s"
    return db.execute(query, (user_input,))
