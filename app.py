from flask import Flask, request, jsonify
from dotenv import load_dotenv
import os
import google.generativeai as genai
import psycopg2
import datetime
import json
import uuid # For session ID generation

load_dotenv()

app = Flask(__name__)

# --- Configuration ---
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")

if not GOOGLE_API_KEY:
    raise ValueError("GOOGLE_API_KEY is not set in the environment variables.")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL is not set in the environment variables.")

genai.configure(api_key=GOOGLE_API_KEY)

# --- Database Helper Functions ---
def get_db_connection():
    conn = psycopg2.connect(DATABASE_URL)
    return conn

# --- System Prompt for Gemini ---
# (This will be refined in a later step)
SYSTEM_PROMPT = """\
あなたは、工場の自動機・半自動機の導入を検討している企業の担当者から、設備仕様に関するヒアリングを行うAIアシスタント「AI設備仕様コンシェルジュ」です。
あなたの目的は、以下の5つの主要な項目について、丁寧かつ専門的にユーザーから情報を引き出すことです。

1.  **目的とワーク（製品）:** どのような目的の設備で、何を扱いたいか。
2.  **生産量（タクトタイム）と自動化レベル:** 1時間あたりの目標生産量、または1つあたりの目標タクトタイム。設備の自動化レベル（全自動、半自動、手動）の希望。
3.  **主要な加工や検査の内容と重要な機能:** 最も中心となる加工や検査は何か。その他に必須または重要な機能は何か。
4.  **設置場所の環境とユーティリティ:** クリーンルームの有無、広さ、搬入経路、電源（単相100V, 三相200Vなど）、エア圧の状況など。
5.  **現状の課題と期待、おおよその予算感:** 現在抱えている課題、設備導入で期待する解決、現時点での大まかな予算。

会話の進め方:
- ユーザーに対して親しみやすく、専門用語を使いすぎない平易な言葉で質問してください。
- 一度に多くのことを聞かず、1〜2つの質問を簡潔に投げかけてください。
- ユーザーの回答が曖昧な場合は、具体例を提示したり、より掘り下げた質問をしたりして、情報を明確にしてください。
- ユーザーがITツールに不慣れな場合も想定し、分かりやすい説明を心がけてください。
- 最終的に上記5項目が概ね明らかになったと判断したら、ヒアリングが完了した旨を伝え (`isComplete: true` を返す)、次のステップ（提案書の確認、担当者からの連絡）について案内してください。
- あなたの応答は、常にJSON形式の `aiResponse` (ユーザーへの表示メッセージ) と `extractedInfo` (抽出情報オブジェクト) を含むようにしてください。`extractedInfo`には上記5項目に対応するキーと、それぞれの情報ステータスや抽出内容、そして全体としてヒアリングが完了したかを示す `isComplete` (boolean) を含めてください。

さあ、最初の挨拶をして、ユーザーにどのような設備を検討しているか尋ねてください。
"""

# --- API Endpoints ---
@app.route('/')
def home():
    return "AI設備仕様コンシェルジュ バックエンド API"

@app.route('/api/chat', methods=['POST'])
def api_chat():
    try:
        data = request.get_json()
        if not data or 'message' not in data:
            return jsonify({"error": "Message is required"}), 400

        user_message = data['message']
        session_history = data.get('currentSessionHistory', []) # フロントエンドから提供される想定

        # Prepare messages for Gemini API
        # The history should be in the format: [{'role': 'user', 'parts': [{'text': '...'}], {'role': 'model', 'parts': [{'text': '...'}]}
        gemini_history = []
        if not session_history: # 最初のメッセージの場合、システムプロンプトをAIの最初の会話として扱う
             gemini_history.append({'role': 'user', 'parts': [{'text': SYSTEM_PROMPT}]})
             # 実際のユーザーの最初の発言は、この後に追加される
        else:
            # システムプロンプトを会話の前提として含める
            # ただし、毎回履歴の先頭に追加すると長くなりすぎるので、GeminiのChatSessionのhistoryに直接含めるか、
            # もしくは、ユーザーメッセージの前に毎回固定で挿入するかを検討。
            # ここでは、Gemini SDKの `start_chat` の `history` にSYSTEM_PROMPTを元にした初期ターンを渡すことを想定し、
            # `session_history` は純粋なユーザーとAIのやり取りとする。
            # より厳密には、SYSTEM_PROMPTの内容をGeminiの'system_instruction'に渡すのが望ましいが、
            # generative-ai SDKのバージョンやモデルによっては直接サポートされていない場合があるため、
            # ここではユーザーメッセージとしてSYSTEM_PROMPTを扱うことで、幅広いモデルに対応しやすくする。
            # 実際の運用では、SDKのドキュメントを確認して最適な方法を選択する。
            gemini_history.extend(session_history)


        gemini_history.append({'role': 'user', 'parts': [{'text': user_message}]})

        # Initialize the generative model
        # TODO: Consider making the model name configurable
        model = genai.GenerativeModel(
            model_name='gemini-1.5-flash-latest', # または gemini-pro など、利用可能なモデル
            # system_instruction=SYSTEM_PROMPT # 最新のSDKではこのようにシステムプロンプトを指定できる場合がある
        )

        # Gemini SDKのChatSessionを使うと文脈管理が容易になる
        # もしSYSTEM_PROMPTをsystem_instructionに渡せない場合、historyの最初に含める
        initial_chat_history_for_gemini = []
        if not session_history: # これがセッションの最初のユーザーメッセージの場合
            # システムプロンプトをユーザーロールの最初のメッセージとしてAIに認識させる
            # AIの最初の応答がSYSTEM_PROMPTに対するものになるように調整
            initial_chat_history_for_gemini = [
                {'role': 'user', 'parts': [{'text': SYSTEM_PROMPT }]},
                {'role': 'model', 'parts': [{'text': "はい、承知いたしました。どのような設備をご希望でしょうか？"}]} # AIの初期応答例
            ]
        initial_chat_history_for_gemini.extend(session_history)


        chat = model.start_chat(history=initial_chat_history_for_gemini)
        response = chat.send_message(user_message)

        ai_response_text = response.text

        # --- AI応答から構造化データを抽出する仮ロジック ---
        # 本来はGeminiのFunction Callingや、より高度なテキスト解析で抽出する。
        # ここでは、キーワードや会話の流れで仮のextractedInfoを生成する。
        extracted_info = {
            "purposeAndWork": None,
            "taktAndAutomation": None,
            "mainProcess": None,
            "environmentAndUtilities": None,
            "issuesAndBudget": None,
            "isComplete": False
        }

        # (仮の抽出ロジック)
        # 実際の抽出はAIの応答内容を解析して行う必要がある。
        # ここでは、ai_response_text に特定のフレーズが含まれていれば、ヒアリングが完了したとみなす。
        # 例: 「ヒアリングが完了しました」というテキストがAIの応答に含まれていれば isComplete を true にする。
        if "ヒアリングが完了しました" in ai_response_text or "提案書を作成します" in ai_response_text:
            extracted_info["isComplete"] = True
            # isCompleteがtrueの場合、各項目に何らかのダミーデータやAIの要約を入れる想定
            # ここでは簡略化のため、AIの最終応答からそれらしいものを探す（本来はもっと複雑）
            # この部分は、実際のAIの応答形式に合わせて調整が必要
            extracted_info["purposeAndWork"] = "AIが抽出した目的とワーク" # 仮
            extracted_info["taktAndAutomation"] = "AIが抽出したタクトと自動化" # 仮
            extracted_info["mainProcess"] = "AIが抽出した主要加工" # 仮
            extracted_info["environmentAndUtilities"] = "AIが抽出した設置環境" # 仮
            extracted_info["issuesAndBudget"] = "AIが抽出した課題と予算" # 仮


        session_id_str = data.get('sessionId')
        is_new_session = False
        if not session_id_str:
            session_id = uuid.uuid4()
            is_new_session = True
        else:
            try:
                session_id = uuid.UUID(session_id_str)
            except ValueError:
                return jsonify({"error": "Invalid sessionId format"}), 400

        conn = None
        try:
            conn = get_db_connection()
            cur = conn.cursor()

            # 1. Manage ChatSession
            if is_new_session:
                cur.execute(
                    "INSERT INTO ChatSessions (session_id, start_time) VALUES (%s, %s)",
                    (session_id, datetime.datetime.now(datetime.timezone.utc))
                )
                app.logger.info(f"New session started: {session_id}")

            # 2. Log user message
            cur.execute(
                "INSERT INTO ChatLogs (session_id, sender, message_content, raw_gemini_request) VALUES (%s, %s, %s, %s)",
                (session_id, 'user', user_message, json.dumps({"user_message": user_message, "history_len": len(initial_chat_history_for_gemini)}))
            )

            # 3. Log AI response
            cur.execute(
                "INSERT INTO ChatLogs (session_id, sender, message_content, raw_gemini_response) VALUES (%s, %s, %s, %s)",
                (session_id, 'ai', ai_response_text, json.dumps(response.parts[0].to_dict() if response.parts else {})) # Storing the first part as dict
            )

            # 4. Save/Update ExtractedInformation (UPSERT)
            # Note: For simplicity, this UPSERT updates all fields.
            # More complex logic might be needed if you want to merge extracted info.
            cur.execute("""
                INSERT INTO ExtractedInformation (
                    session_id, purpose_and_work, takt_and_automation, main_process_and_functions,
                    environment_and_utilities, issues_and_budget, is_complete, raw_extracted_info, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                ON CONFLICT (session_id) DO UPDATE SET
                    purpose_and_work = EXCLUDED.purpose_and_work,
                    takt_and_automation = EXCLUDED.takt_and_automation,
                    main_process_and_functions = EXCLUDED.main_process_and_functions,
                    environment_and_utilities = EXCLUDED.environment_and_utilities,
                    issues_and_budget = EXCLUDED.issues_and_budget,
                    is_complete = EXCLUDED.is_complete,
                    raw_extracted_info = EXCLUDED.raw_extracted_info,
                    updated_at = NOW();
            """, (
                session_id,
                extracted_info.get("purposeAndWork"),
                extracted_info.get("taktAndAutomation"),
                extracted_info.get("mainProcess"),
                extracted_info.get("environmentAndUtilities"),
                extracted_info.get("issuesAndBudget"),
                extracted_info.get("isComplete", False),
                json.dumps(extracted_info) # Store the full extracted_info
            ))
            app.logger.info(f"Extracted info for session {session_id} saved/updated.")

            # 5. If conversation is complete, update ChatSession
            if extracted_info.get("isComplete"):
                cur.execute(
                    "UPDATE ChatSessions SET end_time = %s, final_proposal_summary = %s WHERE session_id = %s",
                    (datetime.datetime.now(datetime.timezone.utc), json.dumps(extracted_info), session_id)
                )
                app.logger.info(f"Session {session_id} marked as complete.")

            conn.commit()
        except psycopg2.Error as db_error:
            app.logger.error(f"Database error in /api/chat: {db_error}")
            if conn:
                conn.rollback()
            # We can choose to still return the AI response to the user even if DB save fails
            # Or return a specific error. For now, let's log and continue.
            # return jsonify({"error": "Database operation failed"}), 500
        except Exception as e_db: # Catch other exceptions during DB operations
            app.logger.error(f"Non-DB Exception during DB operations in /api/chat: {e_db}")
            if conn:
                conn.rollback()
        finally:
            if conn:
                cur.close()
                conn.close()

        return jsonify({
            "aiResponse": ai_response_text,
            "extractedInfo": extracted_info,
            "sessionId": str(session_id) # Return session ID to frontend
        })

    except Exception as e:
        app.logger.error(f"Error in /api/chat: {e}")
        # スタックトレースをログに出力
        import traceback
        app.logger.error(traceback.format_exc())
        return jsonify({"error": str(e)}), 500

@app.route('/api/contact', methods=['POST'])
def api_contact():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    name = data.get('name')
    company_name = data.get('company')
    email = data.get('email')
    phone_number = data.get('phone')
    session_id_str = data.get('sessionId') # 関連するチャットセッションのID

    if not name or not company_name or not email:
        return jsonify({"error": "Missing required fields: name, company, email"}), 400

    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # 1. Insert or Update User
        # Check if user with this email already exists
        cur.execute("SELECT user_id FROM Users WHERE email = %s", (email,))
        user_row = cur.fetchone()

        if user_row:
            user_id = user_row[0]
            # Optionally, update user details if they changed, though not typical for this flow
            cur.execute(
                "UPDATE Users SET name = %s, company_name = %s, phone_number = %s, updated_at = NOW() WHERE user_id = %s",
                (name, company_name, phone_number, user_id)
            )
            app.logger.info(f"User {user_id} updated with new contact submission details.")
        else:
            cur.execute(
                "INSERT INTO Users (name, company_name, email, phone_number) VALUES (%s, %s, %s, %s) RETURNING user_id",
                (name, company_name, email, phone_number)
            )
            user_id = cur.fetchone()[0]
            app.logger.info(f"New user created with ID: {user_id}")

        # 2. Link user_id to ChatSession if sessionId is provided
        if session_id_str:
            try:
                session_uuid = uuid.UUID(session_id_str)
                cur.execute(
                    "UPDATE ChatSessions SET user_id = %s WHERE session_id = %s AND user_id IS NULL", # Update only if not already set
                    (user_id, session_uuid)
                )
                if cur.rowcount > 0:
                    app.logger.info(f"ChatSession {session_uuid} linked to user_id {user_id}.")
                else:
                    app.logger.warning(f"ChatSession {session_uuid} not found or already linked for user_id {user_id}.")
            except ValueError:
                app.logger.warning(f"Invalid sessionId format provided for contact: {session_id_str}")
            except Exception as e_session_link: # More specific error handling if needed
                app.logger.error(f"Error linking session to user: {e_session_link}")


        conn.commit()
        return jsonify({"message": "Contact information received successfully", "userId": user_id}), 201

    except psycopg2.Error as db_error:
        app.logger.error(f"Database error in /api/contact: {db_error}")
        if conn:
            conn.rollback()
        return jsonify({"error": "Database operation failed"}), 500
    except Exception as e:
        app.logger.error(f"Error in /api/contact: {e}")
        import traceback
        app.logger.error(traceback.format_exc())
        if conn:
            conn.rollback() # Ensure rollback on any exception
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            cur.close()
            conn.close()


if __name__ == '__main__':
    # For local development, using Flask's built-in server.
    # For production, use a WSGI server like Gunicorn.
    app.run(debug=True, port=5000)
"""
