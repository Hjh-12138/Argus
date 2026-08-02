def search(db, user_input):
    query = "SELECT * FROM users WHERE name = '" + user_input + "'"
    return db.execute(query)
