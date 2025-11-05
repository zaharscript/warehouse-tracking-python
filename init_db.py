import os
import psycopg2
from urllib.parse import urlparse

# Get DATABASE_URL from Railway
DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL:
    url = urlparse(DATABASE_URL)
    DB_CONFIG = {
        "host": url.hostname,
        "database": url.path[1:],
        "user": url.username,
        "password": url.password,
        "port": url.port or 5432
    }
else:
    # Fallback for local
    DB_CONFIG = {
        "host": os.getenv("DB_HOST", "localhost"),
        "database": os.getenv("DB_NAME", "warehouse_db"),
        "user": os.getenv("DB_USER", "postgres"),
        "password": os.getenv("DB_PASSWORD", ""),
        "port": os.getenv("DB_PORT", "5432")
    }

def init_database():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        
        # Create main warehouse table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS warehouse_db (
                id SERIAL PRIMARY KEY,
                serial_number VARCHAR(255) UNIQUE NOT NULL,
                kanban_location VARCHAR(255),
                status VARCHAR(50),
                last_update_in TIMESTAMP,
                last_update_out TIMESTAMP
            )
        """)
        
        # Create archive table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS warehouse_db_old (
                id SERIAL PRIMARY KEY,
                serial_number VARCHAR(255) NOT NULL,
                kanban_location VARCHAR(255),
                status VARCHAR(50),
                last_update_in TIMESTAMP,
                last_update_out TIMESTAMP
            )
        """)
        
        conn.commit()
        print("✅ Database tables created successfully!")
        
        # Verify tables
        cur.execute("""
            SELECT table_name FROM information_schema.tables 
            WHERE table_schema='public'
        """)
        tables = [t[0] for t in cur.fetchall()]
        print(f"📊 Available tables: {tables}")
        
        conn.close()
        
    except Exception as e:
        print(f"❌ Error initializing database: {e}")

if __name__ == "__main__":
    init_database()