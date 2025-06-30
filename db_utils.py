import os
import psycopg2
import psycopg2.extras # For dict cursor
import logging
from dotenv import load_dotenv

load_dotenv()

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "ai_concierge_db")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

logger = logging.getLogger(__name__)

def get_db_connection():
    """PostgreSQLデータベースへの接続を取得します。"""
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD
        )
        return conn
    except psycopg2.Error as e:
        logger.error(f"データベース接続エラー: {e}")
        raise

def initialize_db():
    """データベースのテーブルを初期化（作成）します。"""
    commands = (
        """
        CREATE TABLE IF NOT EXISTS ChatSessions (
            session_id SERIAL PRIMARY KEY,
            user_id INTEGER, -- UsersテーブルへのFKだが、まだUsersテーブルがないので一旦そのまま
            start_time TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            end_time TIMESTAMP WITH TIME ZONE,
            final_proposal_summary JSONB,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS ChatLogs (
            log_id SERIAL PRIMARY KEY,
            session_id INTEGER NOT NULL REFERENCES ChatSessions(session_id) ON DELETE CASCADE,
            sender VARCHAR(10) NOT NULL, -- "user" or "ai"
            message_content TEXT NOT NULL,
            timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            raw_gemini_request JSONB, -- デバッグ用
            raw_gemini_response JSONB -- デバッグ用
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS ExtractedInformation (
            info_id SERIAL PRIMARY KEY,
            session_id INTEGER NOT NULL REFERENCES ChatSessions(session_id) ON DELETE CASCADE,
            purpose_and_work TEXT,
            takt_and_automation TEXT,
            main_process_and_functions TEXT,
            environment_and_utilities TEXT,
            issues_and_budget TEXT,
            is_complete BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE OR REPLACE FUNCTION update_changetimestamp_column()
        RETURNS TRIGGER AS $$
        BEGIN
           NEW.updated_at = NOW();
           RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """,
        """
        DROP TRIGGER IF EXISTS update_chatsessions_changetimestamp ON ChatSessions;
        CREATE TRIGGER update_chatsessions_changetimestamp
            BEFORE UPDATE ON ChatSessions
            FOR EACH ROW
            EXECUTE PROCEDURE update_changetimestamp_column();
        """,
        """
        DROP TRIGGER IF EXISTS update_extractedinfo_changetimestamp ON ExtractedInformation;
        CREATE TRIGGER update_extractedinfo_changetimestamp
            BEFORE UPDATE ON ExtractedInformation
            FOR EACH ROW
            EXECUTE PROCEDURE update_changetimestamp_column();
        """
    )
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            for command in commands:
                cur.execute(command)
        conn.commit()
        logger.info("データベースの初期化（テーブル作成）が成功しました。")
    except psycopg2.Error as e:
        logger.error(f"データベース初期化エラー: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

# --- ChatSessions ---
def create_chat_session(user_id=None):
    """新しいチャットセッションを作成し、セッションIDを返します。"""
    sql = """
        INSERT INTO ChatSessions (user_id, start_time)
        VALUES (%s, CURRENT_TIMESTAMP) RETURNING session_id;
    """
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(sql, (user_id,))
            session_id = cur.fetchone()[0]
            conn.commit()
            logger.info(f"チャットセッション {session_id} を作成しました。")
            return session_id
    except psycopg2.Error as e:
        logger.error(f"チャットセッション作成エラー: {e}")
        if conn:
            conn.rollback()
        return None
    finally:
        if conn:
            conn.close()

def update_chat_session_summary(session_id, summary_json, is_complete):
    """チャットセッションの最終提案概要と終了時間を更新します。"""
    sql = """
        UPDATE ChatSessions
        SET final_proposal_summary = %s, end_time = CASE WHEN %s THEN CURRENT_TIMESTAMP ELSE NULL END
        WHERE session_id = %s;
    """
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(sql, (psycopg2.extras.Json(summary_json), is_complete, session_id))
            conn.commit()
            logger.info(f"チャットセッション {session_id} の概要を更新しました。")
    except psycopg2.Error as e:
        logger.error(f"チャットセッション概要更新エラー: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

# --- ChatLogs ---
def add_chat_log(session_id, sender, message_content, raw_request=None, raw_response=None):
    """チャットログを追加します。"""
    sql = """
        INSERT INTO ChatLogs (session_id, sender, message_content, raw_gemini_request, raw_gemini_response)
        VALUES (%s, %s, %s, %s, %s);
    """
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(sql, (
                session_id, sender, message_content,
                psycopg2.extras.Json(raw_request) if raw_request else None,
                psycopg2.extras.Json(raw_response) if raw_response else None
            ))
            conn.commit()
            logger.debug(f"チャットログを追加しました (Session: {session_id}, Sender: {sender})")
    except psycopg2.Error as e:
        logger.error(f"チャットログ追加エラー: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

# --- ExtractedInformation ---
def upsert_extracted_information(session_id, info_dict):
    """抽出情報を挿入または更新します。is_completeフラグも更新します。"""
    # まず、該当セッションIDの情報が存在するか確認
    select_sql = "SELECT info_id FROM ExtractedInformation WHERE session_id = %s;"
    insert_sql = """
        INSERT INTO ExtractedInformation (
            session_id, purpose_and_work, takt_and_automation, main_process_and_functions,
            environment_and_utilities, issues_and_budget, is_complete
        ) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING info_id;
    """
    update_sql = """
        UPDATE ExtractedInformation SET
            purpose_and_work = %s, takt_and_automation = %s, main_process_and_functions = %s,
            environment_and_utilities = %s, issues_and_budget = %s, is_complete = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE session_id = %s;
    """
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(select_sql, (session_id,))
            existing_info = cur.fetchone()

            is_complete = info_dict.get('isComplete', False)

            if existing_info:
                # 更新
                cur.execute(update_sql, (
                    info_dict.get('purposeAndWork'), info_dict.get('taktAndAutomation'),
                    info_dict.get('mainProcess'), info_dict.get('environmentAndUtilities'),
                    info_dict.get('issuesAndBudget'), is_complete, session_id
                ))
                logger.info(f"抽出情報を更新しました (Session: {session_id})")
            else:
                # 挿入
                cur.execute(insert_sql, (
                    session_id, info_dict.get('purposeAndWork'), info_dict.get('taktAndAutomation'),
                    info_dict.get('mainProcess'), info_dict.get('environmentAndUtilities'),
                    info_dict.get('issuesAndBudget'), is_complete
                ))
                logger.info(f"抽出情報を新規追加しました (Session: {session_id})")
            conn.commit()
    except psycopg2.Error as e:
        logger.error(f"抽出情報UPSERTエラー: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

def get_latest_extracted_information(session_id):
    """指定されたセッションIDの最新の抽出情報を取得します。"""
    sql = "SELECT * FROM ExtractedInformation WHERE session_id = %s ORDER BY updated_at DESC LIMIT 1;"
    conn = None
    try:
        conn = get_db_connection()
        # 辞書形式で結果を取得するために psycopg2.extras.DictCursor を使用
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(sql, (session_id,))
            record = cur.fetchone()
            if record:
                return dict(record) # DictRowを通常のdictに変換
            return None
    except psycopg2.Error as e:
        logger.error(f"抽出情報取得エラー (Session: {session_id}): {e}")
        return None
    finally:
        if conn:
            conn.close()


if __name__ == '__main__':
    # このスクリプトを直接実行すると、データベースを初期化します。
    # 注意: 既に存在するテーブルは変更されませんが、新しいテーブルは作成されます。
    print("データベースを初期化します...")
    # ログ設定（db_utils.pyを直接実行する場合の簡易設定）
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    # 環境変数が正しく設定されているか確認
    if not all([DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD]):
        logger.error("データベース接続情報が.envファイルに正しく設定されていません。")
        print("エラー: データベース接続情報が.envファイルに正しく設定されていません。")
    else:
        try:
            # 接続テスト
            conn_test = get_db_connection()
            conn_test.close()
            logger.info("データベース接続テスト成功。")
            initialize_db()
            print("データベースの初期化処理が完了しました。ログを確認してください。")
        except psycopg2.Error as e:
            # get_db_connection内で既にロギングされているが、ここでも表示
            print(f"データベース処理中にエラーが発生しました: {e}")
        except Exception as e_gen:
            print(f"予期せぬエラーが発生しました: {e_gen}")

import os
import psycopg2
import psycopg2.extras # For dict cursor
import logging
from dotenv import load_dotenv

load_dotenv()

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "ai_concierge_db")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

logger = logging.getLogger(__name__)

def get_db_connection():
    """PostgreSQLデータベースへの接続を取得します。"""
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD
        )
        return conn
    except psycopg2.Error as e:
        logger.error(f"データベース接続エラー: {e}")
        raise

def initialize_db():
    """データベースのテーブルを初期化（作成）します。"""
    commands = (
        """
        CREATE TABLE IF NOT EXISTS ChatSessions (
            session_id SERIAL PRIMARY KEY,
            user_id INTEGER, -- UsersテーブルへのFKだが、まだUsersテーブルがないので一旦そのまま
            start_time TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            end_time TIMESTAMP WITH TIME ZONE,
            final_proposal_summary JSONB,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS ChatLogs (
            log_id SERIAL PRIMARY KEY,
            session_id INTEGER NOT NULL REFERENCES ChatSessions(session_id) ON DELETE CASCADE,
            sender VARCHAR(10) NOT NULL, -- "user" or "ai"
            message_content TEXT NOT NULL,
            timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            raw_gemini_request JSONB, -- デバッグ用
            raw_gemini_response JSONB -- デバッグ用
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS ExtractedInformation (
            info_id SERIAL PRIMARY KEY,
            session_id INTEGER NOT NULL REFERENCES ChatSessions(session_id) ON DELETE CASCADE,
            purpose_and_work TEXT,
            takt_and_automation TEXT,
            main_process_and_functions TEXT,
            environment_and_utilities TEXT,
            issues_and_budget TEXT,
            is_complete BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE OR REPLACE FUNCTION update_changetimestamp_column()
        RETURNS TRIGGER AS $$
        BEGIN
           NEW.updated_at = NOW();
           RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """,
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'update_chatsessions_changetimestamp') THEN
                CREATE TRIGGER update_chatsessions_changetimestamp
                    BEFORE UPDATE ON ChatSessions
                    FOR EACH ROW
                    EXECUTE PROCEDURE update_changetimestamp_column();
            END IF;
        END $$;
        """,
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'update_extractedinfo_changetimestamp') THEN
                CREATE TRIGGER update_extractedinfo_changetimestamp
                    BEFORE UPDATE ON ExtractedInformation
                    FOR EACH ROW
                    EXECUTE PROCEDURE update_changetimestamp_column();
            END IF;
        END $$;
        """,
        """
        CREATE TABLE IF NOT EXISTS Users (
            user_id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            company_name VARCHAR(255),
            email VARCHAR(255) UNIQUE NOT NULL,
            phone_number VARCHAR(50),
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'update_users_changetimestamp' AND tgrelid = 'users'::regclass) THEN
                CREATE TRIGGER update_users_changetimestamp
                    BEFORE UPDATE ON Users
                    FOR EACH ROW
                    EXECUTE PROCEDURE update_changetimestamp_column();
            END IF;
        END $$;
        """,
        """
        -- ChatSessionsテーブルのuser_idカラムに外部キー制約を追加 (Usersテーブル作成後)
        -- 既に存在するChatSessionsテーブルに対する変更なので、エラーにならないように注意
        DO $$
        BEGIN
            IF EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name='users') AND
               EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name='chatsessions') AND
               NOT EXISTS (
                   SELECT 1 FROM information_schema.table_constraints
                   WHERE constraint_name='fk_chatsessions_user_id' AND table_name='chatsessions'
               )
            THEN
                ALTER TABLE ChatSessions
                ADD CONSTRAINT fk_chatsessions_user_id
                FOREIGN KEY (user_id) REFERENCES Users(user_id) ON DELETE SET NULL;
                RAISE NOTICE 'Foreign key fk_chatsessions_user_id on ChatSessions(user_id) created.';
            ELSE
                RAISE NOTICE 'Skipping creation of foreign key fk_chatsessions_user_id or Users/ChatSessions table does not exist.';
            END IF;
        END $$;
        """
    )
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            for command in commands:
                cur.execute(command)
        conn.commit()
        logger.info("データベースの初期化（テーブル作成）が成功しました。")
    except psycopg2.Error as e:
        logger.error(f"データベース初期化エラー: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

# --- ChatSessions ---
def create_chat_session(user_id=None):
    """新しいチャットセッションを作成し、セッションIDを返します。"""
    sql = """
        INSERT INTO ChatSessions (user_id, start_time)
        VALUES (%s, CURRENT_TIMESTAMP) RETURNING session_id;
    """
    conn = None
    session_id = None # セッションIDを初期化
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(sql, (user_id,))
            result = cur.fetchone()
            if result:
                session_id = result[0]
            conn.commit()
            if session_id:
                logger.info(f"チャットセッション {session_id} を作成しました。")
            else:
                logger.error("チャットセッションの作成に失敗しました（RETURNING session_idが結果を返しませんでした）。")
            return session_id
    except psycopg2.Error as e:
        logger.error(f"チャットセッション作成エラー: {e}")
        if conn:
            conn.rollback()
        return None # エラー時はNoneを返す
    finally:
        if conn:
            conn.close()

def update_chat_session_summary(session_id, summary_json, is_complete):
    """チャットセッションの最終提案概要と終了時間を更新します。"""
    sql = """
        UPDATE ChatSessions
        SET final_proposal_summary = %s, end_time = CASE WHEN %s THEN CURRENT_TIMESTAMP ELSE NULL END, updated_at = CURRENT_TIMESTAMP
        WHERE session_id = %s;
    """
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(sql, (psycopg2.extras.Json(summary_json), is_complete, session_id))
            conn.commit()
            logger.info(f"チャットセッション {session_id} の概要を更新しました。")
    except psycopg2.Error as e:
        logger.error(f"チャットセッション概要更新エラー: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

# --- ChatLogs ---
def add_chat_log(session_id, sender, message_content, raw_request=None, raw_response=None):
    """チャットログを追加します。"""
    sql = """
        INSERT INTO ChatLogs (session_id, sender, message_content, raw_gemini_request, raw_gemini_response)
        VALUES (%s, %s, %s, %s, %s);
    """
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(sql, (
                session_id, sender, message_content,
                psycopg2.extras.Json(raw_request) if raw_request else None,
                psycopg2.extras.Json(raw_response) if raw_response else None
            ))
            conn.commit()
            logger.debug(f"チャットログを追加しました (Session: {session_id}, Sender: {sender})")
    except psycopg2.Error as e:
        logger.error(f"チャットログ追加エラー: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

# --- ExtractedInformation ---
def upsert_extracted_information(session_id, info_dict):
    """抽出情報を挿入または更新します。is_completeフラグも更新します。"""
    select_sql = "SELECT info_id FROM ExtractedInformation WHERE session_id = %s;"
    insert_sql = """
        INSERT INTO ExtractedInformation (
            session_id, purpose_and_work, takt_and_automation, main_process_and_functions,
            environment_and_utilities, issues_and_budget, is_complete, created_at, updated_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) RETURNING info_id;
    """
    update_sql = """
        UPDATE ExtractedInformation SET
            purpose_and_work = %s, takt_and_automation = %s, main_process_and_functions = %s,
            environment_and_utilities = %s, issues_and_budget = %s, is_complete = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE session_id = %s;
    """
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(select_sql, (session_id,))
            existing_info = cur.fetchone()

            is_complete = info_dict.get('isComplete', False)

            if existing_info:
                cur.execute(update_sql, (
                    info_dict.get('purposeAndWork'), info_dict.get('taktAndAutomation'),
                    info_dict.get('mainProcess'), info_dict.get('environmentAndUtilities'),
                    info_dict.get('issuesAndBudget'), is_complete, session_id
                ))
                logger.info(f"抽出情報を更新しました (Session: {session_id})")
            else:
                cur.execute(insert_sql, (
                    session_id, info_dict.get('purposeAndWork'), info_dict.get('taktAndAutomation'),
                    info_dict.get('mainProcess'), info_dict.get('environmentAndUtilities'),
                    info_dict.get('issuesAndBudget'), is_complete
                ))
                logger.info(f"抽出情報を新規追加しました (Session: {session_id})")
            conn.commit()
    except psycopg2.Error as e:
        logger.error(f"抽出情報UPSERTエラー: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

def get_latest_extracted_information(session_id):
    """指定されたセッションIDの最新の抽出情報を取得します。"""
    sql = "SELECT * FROM ExtractedInformation WHERE session_id = %s ORDER BY updated_at DESC LIMIT 1;"
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(sql, (session_id,))
            record = cur.fetchone()
            if record:
                return dict(record)
            return None
    except psycopg2.Error as e:
        logger.error(f"抽出情報取得エラー (Session: {session_id}): {e}")
        return None
    finally:
        if conn:
            conn.close()


if __name__ == '__main__':
    print("データベースを初期化します...")
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    if not all([DB_USER, DB_PASSWORD, DB_NAME]): # DB_HOST, DB_PORTはデフォルト値があるので必須チェックから外す場合もある
        logger.error("データベース接続情報（ユーザー名、パスワード、データベース名）が.envファイルに正しく設定されていません。")
        print("エラー: データベース接続情報（ユーザー名、パスワード、データベース名）が.envファイルに正しく設定されていません。")
    else:
        try:
            conn_test = get_db_connection()
            logger.info(f"データベース ({DB_NAME} on {DB_HOST}:{DB_PORT}) 接続テスト成功。")
            conn_test.close()
            initialize_db()
            print("データベースの初期化処理が完了しました。ログを確認してください。")
        except psycopg2.OperationalError as e:
            logger.error(f"データベース接続運用エラー: {e}")
            print(f"データベース接続運用エラーです。設定やDBサーバーの状態を確認してください: {e}")
        except psycopg2.Error as e:
            logger.error(f"データベース処理中にエラーが発生しました: {e}")
            print(f"データベース処理中にエラーが発生しました: {e}")
        except Exception as e_gen:
            logger.error(f"予期せぬエラーが発生しました: {e_gen}")
            print(f"予期せぬエラーが発生しました: {e_gen}")

import os
import psycopg2
import psycopg2.extras # For dict cursor
import logging
from dotenv import load_dotenv

load_dotenv()

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "ai_concierge_db")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

logger = logging.getLogger(__name__)

def get_db_connection():
    """PostgreSQLデータベースへの接続を取得します。"""
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD
        )
        return conn
    except psycopg2.Error as e:
        logger.error(f"データベース接続エラー: {e}")
        raise

def initialize_db():
    """データベースのテーブルを初期化（作成）します。"""
    commands = (
        """
        CREATE TABLE IF NOT EXISTS ChatSessions (
            session_id SERIAL PRIMARY KEY,
            user_id INTEGER, -- UsersテーブルへのFKだが、まだUsersテーブルがないので一旦そのまま
            start_time TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            end_time TIMESTAMP WITH TIME ZONE,
            final_proposal_summary JSONB,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS ChatLogs (
            log_id SERIAL PRIMARY KEY,
            session_id INTEGER NOT NULL REFERENCES ChatSessions(session_id) ON DELETE CASCADE,
            sender VARCHAR(10) NOT NULL, -- "user" or "ai"
            message_content TEXT NOT NULL,
            timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            raw_gemini_request JSONB, -- デバッグ用
            raw_gemini_response JSONB -- デバッグ用
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS ExtractedInformation (
            info_id SERIAL PRIMARY KEY,
            session_id INTEGER NOT NULL REFERENCES ChatSessions(session_id) ON DELETE CASCADE,
            purpose_and_work TEXT,
            takt_and_automation TEXT,
            main_process_and_functions TEXT,
            environment_and_utilities TEXT,
            issues_and_budget TEXT,
            is_complete BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE OR REPLACE FUNCTION update_changetimestamp_column()
        RETURNS TRIGGER AS $$
        BEGIN
           NEW.updated_at = NOW();
           RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """,
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'update_chatsessions_changetimestamp' AND tgrelid = 'chatsessions'::regclass) THEN
                CREATE TRIGGER update_chatsessions_changetimestamp
                    BEFORE UPDATE ON ChatSessions
                    FOR EACH ROW
                    EXECUTE PROCEDURE update_changetimestamp_column();
            END IF;
        END $$;
        """,
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'update_extractedinfo_changetimestamp' AND tgrelid = 'extractedinformation'::regclass) THEN
                CREATE TRIGGER update_extractedinfo_changetimestamp
                    BEFORE UPDATE ON ExtractedInformation
                    FOR EACH ROW
                    EXECUTE PROCEDURE update_changetimestamp_column();
            END IF;
        END $$;
        """
    )
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            for command in commands:
                cur.execute(command)
        conn.commit()
        logger.info("データベースの初期化（テーブル作成）が成功しました。")
    except psycopg2.Error as e:
        logger.error(f"データベース初期化エラー: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

# --- ChatSessions ---
def create_chat_session(user_id=None):
    """新しいチャットセッションを作成し、セッションIDを返します。"""
    sql = """
        INSERT INTO ChatSessions (user_id, start_time, created_at, updated_at)
        VALUES (%s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) RETURNING session_id;
    """
    conn = None
    session_id = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(sql, (user_id,))
            result = cur.fetchone()
            if result:
                session_id = result[0]
            conn.commit()
            if session_id:
                logger.info(f"チャットセッション {session_id} を作成しました。")
            else:
                logger.error("チャットセッションの作成に失敗しました（RETURNING session_idが結果を返しませんでした）。")
            return session_id
    except psycopg2.Error as e:
        logger.error(f"チャットセッション作成エラー: {e}")
        if conn:
            conn.rollback()
        return None
    finally:
        if conn:
            conn.close()

def update_chat_session_summary(session_id, summary_json, is_complete):
    """チャットセッションの最終提案概要と終了時間を更新します。"""
    sql = """
        UPDATE ChatSessions
        SET final_proposal_summary = %s,
            end_time = CASE WHEN %s THEN CURRENT_TIMESTAMP ELSE NULL END
        WHERE session_id = %s;
    """
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            # psycopg2.extras.Jsonを使ってJSONオブジェクトを適切に処理
            cur.execute(sql, (psycopg2.extras.Json(summary_json) if summary_json else None, is_complete, session_id))
            conn.commit()
            logger.info(f"チャットセッション {session_id} の概要を更新しました。")
    except psycopg2.Error as e:
        logger.error(f"チャットセッション概要更新エラー: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

# --- ChatLogs ---
def add_chat_log(session_id, sender, message_content, raw_request=None, raw_response=None):
    """チャットログを追加します。"""
    sql = """
        INSERT INTO ChatLogs (session_id, sender, message_content, raw_gemini_request, raw_gemini_response, timestamp)
        VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP);
    """
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(sql, (
                session_id, sender, message_content,
                psycopg2.extras.Json(raw_request) if raw_request else None,
                psycopg2.extras.Json(raw_response) if raw_response else None
            ))
            conn.commit()
            logger.debug(f"チャットログを追加しました (Session: {session_id}, Sender: {sender})")
    except psycopg2.Error as e:
        logger.error(f"チャットログ追加エラー: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

# --- ExtractedInformation ---
def upsert_extracted_information(session_id, info_dict):
    """抽出情報を挿入または更新します。is_completeフラグも更新します。"""
    select_sql = "SELECT info_id FROM ExtractedInformation WHERE session_id = %s;"
    insert_sql = """
        INSERT INTO ExtractedInformation (
            session_id, purpose_and_work, takt_and_automation, main_process_and_functions,
            environment_and_utilities, issues_and_budget, is_complete, created_at, updated_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) RETURNING info_id;
    """
    update_sql = """
        UPDATE ExtractedInformation SET
            purpose_and_work = %s, takt_and_automation = %s, main_process_and_functions = %s,
            environment_and_utilities = %s, issues_and_budget = %s, is_complete = %s
        WHERE session_id = %s;
    """
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(select_sql, (session_id,))
            existing_info = cur.fetchone()

            is_complete = info_dict.get('isComplete', False) if isinstance(info_dict.get('isComplete'), bool) else False

            params = (
                info_dict.get('purposeAndWork'), info_dict.get('taktAndAutomation'),
                info_dict.get('mainProcess'), info_dict.get('environmentAndUtilities'),
                info_dict.get('issuesAndBudget'), is_complete
            )

            if existing_info:
                cur.execute(update_sql, params + (session_id,))
                logger.info(f"抽出情報を更新しました (Session: {session_id})")
            else:
                cur.execute(insert_sql, (session_id,) + params)
                logger.info(f"抽出情報を新規追加しました (Session: {session_id})")
            conn.commit()
    except psycopg2.Error as e:
        logger.error(f"抽出情報UPSERTエラー: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

def get_latest_extracted_information(session_id):
    """指定されたセッションIDの最新の抽出情報を取得します。"""
    sql = "SELECT * FROM ExtractedInformation WHERE session_id = %s ORDER BY updated_at DESC LIMIT 1;"
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(sql, (session_id,))
            record = cur.fetchone()
            if record:
                return dict(record)
            return None
    except psycopg2.Error as e:
        logger.error(f"抽出情報取得エラー (Session: {session_id}): {e}")
        return None
    finally:
        if conn:
            conn.close()


if __name__ == '__main__':
    print("データベースを初期化（テーブル作成・更新）します...")
    # __name__ をロガー名として使用
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    if not all([DB_USER, DB_PASSWORD, DB_NAME]):
        logger.error("データベース接続情報（ユーザー名、パスワード、データベース名）が.envファイルに正しく設定されていません。")
        print("エラー: データベース接続情報（ユーザー名、パスワード、データベース名）が.envファイルに正しく設定されていません。")
    else:
        try:
            conn_test = get_db_connection()
            logger.info(f"データベース ({DB_NAME} on {DB_HOST}:{DB_PORT}) 接続テスト成功。")
            conn_test.close()
            initialize_db() # テーブル作成/更新処理
            print("データベースの初期化処理が完了しました。詳細はログを確認してください。")
        except psycopg2.OperationalError as e: # 接続自体に失敗した場合など
            logger.error(f"データベース接続運用エラー: {e}")
            print(f"データベース接続運用エラーです。ホスト名、ポート、DB名、認証情報、DBサーバの状態を確認してください: {e}")
        except psycopg2.Error as e: # その他のpsycopg2関連エラー
            logger.error(f"データベース処理中にエラーが発生しました: {e}")
            print(f"データベース処理中にエラーが発生しました: {e}")
        except Exception as e_gen: # 予期せぬその他のエラー
            logger.error(f"予期せぬエラーが発生しました: {e_gen}", exc_info=True)
            print(f"予期せぬエラーが発生しました: {e_gen}")

# --- Users (Customers) ---
def add_user(name, company_name, email, phone_number=None, session_id_to_link=None):
    """新しいユーザーを登録し、ユーザーIDを返します。
       オプションで既存のチャットセッションにユーザーIDを紐付けます。
    """
    user_sql = """
        INSERT INTO Users (name, company_name, email, phone_number, created_at, updated_at)
        VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ON CONFLICT (email) DO UPDATE SET
            name = EXCLUDED.name,
            company_name = EXCLUDED.company_name,
            phone_number = EXCLUDED.phone_number,
            updated_at = CURRENT_TIMESTAMP
        RETURNING user_id;
    """
    update_session_sql = "UPDATE ChatSessions SET user_id = %s WHERE session_id = %s;"
    conn = None
    user_id = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(user_sql, (name, company_name, email, phone_number))
            user_id_result = cur.fetchone()
            if user_id_result:
                user_id = user_id_result[0]
                logger.info(f"ユーザー {user_id} ({email}) を登録または更新しました。")

                if user_id and session_id_to_link:
                    cur.execute(update_session_sql, (user_id, session_id_to_link))
                    logger.info(f"チャットセッション {session_id_to_link} にユーザーID {user_id} を紐付けました。")
            else:
                logger.error(f"ユーザー ({email}) の登録または更新に失敗しました。")

            conn.commit()
        return user_id
    except psycopg2.Error as e:
        logger.error(f"ユーザー登録/更新エラー (Email: {email}): {e}")
        if conn:
            conn.rollback()
        return None
    finally:
        if conn:
            conn.close()
