import sqlite3

def dump_db():
    conn = sqlite3.connect("data/journal.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    print("=== APPS ===")
    cursor.execute("SELECT * FROM build_apps")
    for row in cursor.fetchall():
        print(dict(row))
        
    print("\n=== VERSIONS ===")
    cursor.execute("SELECT * FROM build_versions")
    for row in cursor.fetchall():
        print(dict(row))
        
    conn.close()

if __name__ == "__main__":
    dump_db()
