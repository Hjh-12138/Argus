def search(db, term):
    query = "SELECT * FROM products WHERE name = '" + term + "'"
    return db.execute(query)
