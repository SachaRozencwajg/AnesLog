
import sqlite3

def migrate():
    conn = sqlite3.connect('aneslog.db')
    cursor = conn.cursor()
    
    # List of columns to add
    columns = [
        ("semester", "INTEGER"),
        ("start_date", "DATETIME"),
        ("end_date", "DATETIME"),
        ("institution", "VARCHAR(255)")
    ]
    
    for col_name, col_type in columns:
        try:
            cursor.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_type}")
            print(f"Added column {col_name}")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e):
                print(f"Column {col_name} already exists")
            else:
                print(f"Error adding {col_name}: {e}")
                
    conn.commit()
    conn.close()

if __name__ == "__main__":
    migrate()
