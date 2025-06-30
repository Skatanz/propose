import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL is not set in the environment variables. Please set it in your .env file.")

def initialize_database():
    """Connects to the PostgreSQL database and creates tables if they don't exist."""
    conn = None
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()

        # Create Users (or Customers) table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS Users (
                user_id SERIAL PRIMARY KEY,
                name VARCHAR(255),
                company_name VARCHAR(255),
                email VARCHAR(255) UNIQUE,
                phone_number VARCHAR(50),
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
        """)
        print("Table 'Users' checked/created successfully.")

        # Create ChatSessions table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ChatSessions (
                session_id UUID PRIMARY KEY,
                user_id INTEGER REFERENCES Users(user_id) ON DELETE SET NULL,
                start_time TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                end_time TIMESTAMP WITH TIME ZONE,
                final_proposal_summary JSONB,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
        """)
        print("Table 'ChatSessions' checked/created successfully.")

        # Create ChatLogs table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ChatLogs (
                log_id SERIAL PRIMARY KEY,
                session_id UUID REFERENCES ChatSessions(session_id) ON DELETE CASCADE NOT NULL,
                sender VARCHAR(10) NOT NULL CHECK (sender IN ('user', 'ai')), -- 'user' or 'ai'
                message_content TEXT NOT NULL,
                timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                raw_gemini_request JSONB, -- For debugging
                raw_gemini_response JSONB -- For debugging
            );
        """)
        print("Table 'ChatLogs' checked/created successfully.")

        # Create ExtractedInformation table
        # This table will store the evolution of extracted info per session.
        # A simpler approach could be to just store the final version in ChatSessions.final_proposal_summary.
        # However, storing snapshots can be useful for analysis or if the AI needs to backtrack.
        # For now, we'll keep it as a separate table, assuming updates will create new rows or update existing based on session_id.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ExtractedInformation (
                info_id SERIAL PRIMARY KEY,
                session_id UUID REFERENCES ChatSessions(session_id) ON DELETE CASCADE NOT NULL,
                purpose_and_work TEXT,
                takt_and_automation TEXT,
                main_process_and_functions TEXT,
                environment_and_utilities TEXT,
                issues_and_budget TEXT,
                is_complete BOOLEAN DEFAULT FALSE,
                raw_extracted_info JSONB, -- Store the full JSON from AI if needed
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
        """)
        # Add a unique constraint to ensure only one active (or latest) ExtractedInformation per session
        # This might be better handled by application logic (UPSERT)
        # cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_active_extracted_info ON ExtractedInformation (session_id) WHERE is_latest_version = TRUE;")
        print("Table 'ExtractedInformation' checked/created successfully.")


        # --- Triggers for updated_at ---
        # Function to update 'updated_at' column
        cur.execute("""
            CREATE OR REPLACE FUNCTION trigger_set_timestamp()
            RETURNS TRIGGER AS $$
            BEGIN
              NEW.updated_at = NOW();
              RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
        """)

        # Apply trigger to ChatSessions
        cur.execute("""
            DROP TRIGGER IF EXISTS set_timestamp_chat_sessions ON ChatSessions;
            CREATE TRIGGER set_timestamp_chat_sessions
            BEFORE UPDATE ON ChatSessions
            FOR EACH ROW
            EXECUTE PROCEDURE trigger_set_timestamp();
        """)
        print("Trigger 'set_timestamp_chat_sessions' created successfully.")

        # Apply trigger to ExtractedInformation
        cur.execute("""
            DROP TRIGGER IF EXISTS set_timestamp_extracted_information ON ExtractedInformation;
            CREATE TRIGGER set_timestamp_extracted_information
            BEFORE UPDATE ON ExtractedInformation
            FOR EACH ROW
            EXECUTE PROCEDURE trigger_set_timestamp();
        """)
        print("Trigger 'set_timestamp_extracted_information' created successfully.")

        conn.commit()
        cur.close()
        print("Database initialization complete.")

    except psycopg2.Error as e:
        print(f"Error connecting to or initializing database: {e}")
        if conn:
            conn.rollback() # Rollback any changes if an error occurred
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    print("Initializing database...")
    initialize_database()
    print("If no errors, database schema should be ready.")
    print("Please ensure your DATABASE_URL in .env is correctly configured.")
    print("Example DATABASE_URL: postgresql://username:password@localhost:5432/mydatabase")