import os
import mysql.connector
import logging
import json # JSON文字列をDBに保存するために使用
from dotenv import load_dotenv

load_dotenv()

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "3306") # MySQLのデフォルトポート
DB_NAME = os.getenv("DB_NAME", "ai_concierge_db")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

logger = logging.getLogger(__name__)

def get_db_connection():
    """MySQLデータベースへの接続を取得します。"""
    try:
        conn = mysql.connector.connect(
            host=DB_HOST,
            port=DB_PORT,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD
        )
        return conn
    except mysql.connector.Error as e:
        logger.error(f"MySQLデータベース接続エラー: {e}")
        raise

def initialize_db():
    """MySQLデータベースのテーブルを初期化（作成）します。"""
    # MySQLでは updated_at カラムはテーブル定義で自動更新を設定可能
    # created_at も同様
    # JSON型はそのままJSON型として定義
    # AUTO_INCREMENT を使用
    commands = (
        """
        CREATE TABLE IF NOT EXISTS Users (
            user_id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            company_name VARCHAR(255),
            email VARCHAR(255) UNIQUE NOT NULL,
            phone_number VARCHAR(50),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """,
        """
        CREATE TABLE IF NOT EXISTS ChatSessions (
            session_id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT,
            start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            end_time TIMESTAMP NULL, -- NULLを許容
            final_proposal_summary JSON,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES Users(user_id) ON DELETE SET NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """,
        """
        CREATE TABLE IF NOT EXISTS ChatLogs (
            log_id INT AUTO_INCREMENT PRIMARY KEY,
            session_id INT NOT NULL,
            sender VARCHAR(10) NOT NULL, -- "user" or "ai"
            message_content TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            raw_gemini_request JSON,
            raw_gemini_response JSON,
            FOREIGN KEY (session_id) REFERENCES ChatSessions(session_id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """,
        """
        CREATE TABLE IF NOT EXISTS ExtractedInformation (
            info_id INT AUTO_INCREMENT PRIMARY KEY,
            session_id INT NOT NULL,
            purpose_and_work TEXT,
            takt_and_automation TEXT,
            main_process_and_functions TEXT,
            environment_and_utilities TEXT,
            issues_and_budget TEXT,
            is_complete BOOLEAN DEFAULT FALSE,
            -- result.html向け追加情報
            deviceName TEXT,
            overview TEXT,
            mainFunctions JSON, -- リストはJSONとして保存
            environment JSON,   -- リストはJSONとして保存
            expectations TEXT,
            budget TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES ChatSessions(session_id) ON DELETE CASCADE,
            UNIQUE KEY (session_id) -- 1セッション1レコードを保証する場合 (UPSERTの挙動に依存)
                                     -- もし履歴を残したいならこのUNIQUE KEYは不要
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """
    )
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        for command in commands:
            try:
                cursor.execute(command)
                logger.debug(f"Executed SQL command: {command.strip()[:100]}...") # 長いので一部表示
            except mysql.connector.Error as e:
                # 特定のエラー(例: FK制約で参照先テーブルがまだないなど)はここでは無視せず、ログに出力
                logger.error(f"SQL実行エラー: {e} \nCOMMAND: {command}")
                # 初期化の途中でエラーが出たら、残りのコマンドも実行せずに終了する方が安全かもしれない
                raise # エラーを再送出して呼び出し元で処理
        conn.commit()
        logger.info("MySQLデータベースの初期化（テーブル作成）が成功しました。")
    except mysql.connector.Error as e:
        logger.error(f"MySQLデータベース初期化エラー: {e}")
        # conn.rollback() は mysql-connector-python では自動的に行われることが多いが、明示してもよい
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()

# --- ChatSessions ---
def create_chat_session(user_id=None):
    """新しいチャットセッションを作成し、セッションIDを返します。"""
    sql = "INSERT INTO ChatSessions (user_id, start_time) VALUES (%s, CURRENT_TIMESTAMP);"
    conn = None
    session_id = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(sql, (user_id,))
        session_id = cursor.lastrowid # AUTO_INCREMENTで生成されたIDを取得
        conn.commit()
        if session_id:
            logger.info(f"MySQLチャットセッション {session_id} を作成しました。")
        else:
            logger.error("MySQLチャットセッションの作成に失敗しました (lastrowid is null)。")
        return session_id
    except mysql.connector.Error as e:
        logger.error(f"MySQLチャットセッション作成エラー: {e}")
        # conn.rollback()
        return None
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()

def update_chat_session_summary(session_id, summary_json, is_complete):
    """チャットセッションの最終提案概要と終了時間を更新します。"""
    # summary_jsonがPythonのdictの場合、json.dumpsで文字列に変換
    summary_str = json.dumps(summary_json) if isinstance(summary_json, dict) else summary_json

    sql = """
        UPDATE ChatSessions
        SET final_proposal_summary = %s, end_time = CASE WHEN %s THEN CURRENT_TIMESTAMP ELSE NULL END
        WHERE session_id = %s;
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(sql, (summary_str, is_complete, session_id))
        conn.commit()
        logger.info(f"MySQLチャットセッション {session_id} の概要を更新しました。")
    except mysql.connector.Error as e:
        logger.error(f"MySQLチャットセッション概要更新エラー: {e}")
        # conn.rollback()
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()

# --- ChatLogs ---
def add_chat_log(session_id, sender, message_content, raw_request=None, raw_response=None):
    """チャットログを追加します。"""
    # raw_request/responseがdictならJSON文字列に変換
    raw_request_str = json.dumps(raw_request) if isinstance(raw_request, dict) else raw_request
    raw_response_str = json.dumps(raw_response) if isinstance(raw_response, dict) else raw_response

    sql = """
        INSERT INTO ChatLogs (session_id, sender, message_content, raw_gemini_request, raw_gemini_response)
        VALUES (%s, %s, %s, %s, %s);
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(sql, (
            session_id, sender, message_content,
            raw_request_str, raw_response_str
        ))
        conn.commit()
        logger.debug(f"MySQLチャットログを追加しました (Session: {session_id}, Sender: {sender})")
    except mysql.connector.Error as e:
        logger.error(f"MySQLチャットログ追加エラー: {e}")
        # conn.rollback()
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()

# --- ExtractedInformation ---
def upsert_extracted_information(session_id, info_dict):
    """抽出情報を挿入または更新します。MySQLのON DUPLICATE KEY UPDATEを使用。"""
    # mainFunctions と environment がリストの場合、JSON文字列に変換
    main_functions_str = json.dumps(info_dict.get('mainFunctions')) if isinstance(info_dict.get('mainFunctions'), list) else info_dict.get('mainFunctions')
    environment_str = json.dumps(info_dict.get('environment')) if isinstance(info_dict.get('environment'), list) else info_dict.get('environment')

    # is_complete は BOOLEAN (MySQLではTINYINT(1)) なのでそのまま
    is_complete_val = 1 if info_dict.get('isComplete') else 0


    # ExtractedInformationテーブルに session_id の UNIQUE KEY がある前提
    sql = """
        INSERT INTO ExtractedInformation (
            session_id, purpose_and_work, takt_and_automation, main_process_and_functions,
            environment_and_utilities, issues_and_budget, is_complete,
            deviceName, overview, mainFunctions, environment, expectations, budget
        ) VALUES (
            %(session_id)s, %(purposeAndWork)s, %(taktAndAutomation)s, %(mainProcess)s,
            %(environmentAndUtilities)s, %(issuesAndBudget)s, %(isComplete)s,
            %(deviceName)s, %(overview)s, %(mainFunctions)s, %(environment)s, %(expectations)s, %(budget)s
        )
        ON DUPLICATE KEY UPDATE
            purpose_and_work = VALUES(purpose_and_work),
            takt_and_automation = VALUES(takt_and_automation),
            main_process_and_functions = VALUES(main_process_and_functions),
            environment_and_utilities = VALUES(environment_and_utilities),
            issues_and_budget = VALUES(issues_and_budget),
            is_complete = VALUES(is_complete),
            deviceName = VALUES(deviceName),
            overview = VALUES(overview),
            mainFunctions = VALUES(mainFunctions),
            environment = VALUES(environment),
            expectations = VALUES(expectations),
            budget = VALUES(budget),
            updated_at = CURRENT_TIMESTAMP;
    """
    params = {
        'session_id': session_id,
        'purposeAndWork': info_dict.get('purposeAndWork'),
        'taktAndAutomation': info_dict.get('taktAndAutomation'),
        'mainProcess': info_dict.get('mainProcess'),
        'environmentAndUtilities': info_dict.get('environmentAndUtilities'),
        'issuesAndBudget': info_dict.get('issuesAndBudget'),
        'isComplete': is_complete_val,
        'deviceName': info_dict.get('deviceName'),
        'overview': info_dict.get('overview'),
        'mainFunctions': main_functions_str,
        'environment': environment_str,
        'expectations': info_dict.get('expectations'),
        'budget': info_dict.get('budget')
    }
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(sql, params)
        conn.commit()
        if cursor.lastrowid: # INSERTの場合
             logger.info(f"MySQL抽出情報を新規追加しました (Session: {session_id}, ID: {cursor.lastrowid})")
        else: # UPDATEの場合 (あるいはlastrowidが0を返すケース)
             logger.info(f"MySQL抽出情報を更新しました (Session: {session_id})")

    except mysql.connector.Error as e:
        logger.error(f"MySQL抽出情報UPSERTエラー (Session: {session_id}): {e}")
        # conn.rollback()
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()


def get_latest_extracted_information(session_id):
    """指定されたセッションIDの最新の抽出情報を取得します。
       MySQLではExtractedInformationはUPSERTされるので、通常は1レコードのはず。
    """
    sql = "SELECT * FROM ExtractedInformation WHERE session_id = %s;"
    conn = None
    try:
        conn = get_db_connection()
        # 辞書形式で結果を取得するために cursor(dictionary=True) を使用
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql, (session_id,))
        record = cursor.fetchone()
        if record:
            # JSON文字列で保存されている可能性のある mainFunctions と environment をPythonリストに変換
            if isinstance(record.get('mainFunctions'), str):
                try:
                    record['mainFunctions'] = json.loads(record['mainFunctions'])
                except json.JSONDecodeError:
                    logger.warning(f"Failed to parse mainFunctions JSON for session {session_id}")
                    record['mainFunctions'] = [] # パース失敗時は空リスト
            if isinstance(record.get('environment'), str):
                try:
                    record['environment'] = json.loads(record['environment'])
                except json.JSONDecodeError:
                    logger.warning(f"Failed to parse environment JSON for session {session_id}")
                    record['environment'] = [] # パース失敗時は空リスト
            return record
        return None
    except mysql.connector.Error as e:
        logger.error(f"MySQL抽出情報取得エラー (Session: {session_id}): {e}")
        return None
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()

# --- Users (Customers) ---
def add_user(name, company_name, email, phone_number=None, session_id_to_link=None):
    """新しいユーザーを登録または更新し、ユーザーIDを返します。
       オプションで既存のチャットセッションにユーザーIDを紐付けます。
    """
    user_sql = """
        INSERT INTO Users (name, company_name, email, phone_number)
        VALUES (%s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            name = VALUES(name),
            company_name = VALUES(company_name),
            phone_number = VALUES(phone_number),
            updated_at = CURRENT_TIMESTAMP;
    """
    # ON DUPLICATE KEY UPDATE の後、user_id を取得するために別途SELECTが必要
    select_user_sql = "SELECT user_id FROM Users WHERE email = %s;"
    update_session_sql = "UPDATE ChatSessions SET user_id = %s WHERE session_id = %s;"

    conn = None
    user_id = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(user_sql, (name, company_name, email, phone_number))

        # 挿入または更新された行のIDを取得
        if cursor.lastrowid: # INSERTの場合
            user_id = cursor.lastrowid
        else: # UPDATEの場合、または lastrowid が0を返す場合
            cursor.execute(select_user_sql, (email,))
            result = cursor.fetchone()
            if result:
                user_id = result[0]

        if user_id:
            logger.info(f"MySQLユーザー {user_id} ({email}) を登録または更新しました。")
            if session_id_to_link:
                cursor.execute(update_session_sql, (user_id, session_id_to_link))
                logger.info(f"MySQLチャットセッション {session_id_to_link} にユーザーID {user_id} を紐付けました。")
        else:
            logger.error(f"MySQLユーザー ({email}) の登録/更新後のID取得に失敗しました。")

        conn.commit()
        return user_id
    except mysql.connector.Error as e:
        logger.error(f"MySQLユーザー登録/更新エラー (Email: {email}): {e}")
        # conn.rollback()
        return None
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()


if __name__ == '__main__':
    print("MySQLデータベースユーティリティ: 初期化テスト")
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    if not all([DB_USER, DB_PASSWORD, DB_NAME]):
        logger.error("データベース接続情報（ユーザー名、パスワード、データベース名）が.envファイルに正しく設定されていません。")
    else:
        try:
            conn_test = get_db_connection()
            logger.info(f"MySQLデータベース ({DB_NAME} on {DB_HOST}:{DB_PORT}) 接続テスト成功。")
            conn_test.close()

            logger.info("初期化処理(initialize_db)を実行します...")
            initialize_db()
            logger.info("初期化処理が完了しました。")

            # ここに簡単なテストコードを追加することも可能
            # 例: test_session_id = create_chat_session()
            #     if test_session_id:
            #         logger.info(f"Test session created: {test_session_id}")
            #         # ... add_chat_log, upsert_extracted_informationなどのテスト ...

        except mysql.connector.Error as e:
            logger.error(f"MySQLデータベース処理中にエラー: {e}")
        except Exception as e_gen:
            logger.error(f"予期せぬエラー: {e_gen}", exc_info=True)
