import os
import pymysql

def run_migration():
    """Create the `maintenance_notes` table if it does not exist.
    Uses environment variables for DB connection (same as other scripts).
    """
    conn = pymysql.connect(
        host=os.getenv('DB_HOST'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME'),
    )
    try:
        with conn.cursor() as cur:
            cur.execute('''
                CREATE TABLE IF NOT EXISTS maintenance_notes (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    user_id INT NULL,
                    note TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_maintenance_notes_user_created (user_id, created_at)
                );
            ''')
            try:
                cur.execute('ALTER TABLE maintenance_notes ADD COLUMN user_id INT NULL')
            except Exception:
                pass
            try:
                cur.execute('CREATE INDEX idx_maintenance_notes_user_created ON maintenance_notes (user_id, created_at DESC)')
            except Exception:
                pass
        conn.commit()
        print('Migration applied: maintenance_notes table ready.')
    finally:
        conn.close()

if __name__ == '__main__':
    run_migration()
