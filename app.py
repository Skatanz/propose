import os
import json
import logging
from flask import Flask, request, jsonify, session
from dotenv import load_dotenv
import google.generativeai as genai
import db_utils # データベースユーティリティモジュール

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "your_default_secret_key") # セッション管理用のシークレットキー

# ロギング設定
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# Gemini APIキーの設定（環境変数から取得）
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
if not GOOGLE_API_KEY:
    logger.warning("警告: GOOGLE_API_KEYが設定されていません。Gemini API連携は機能しません。")
else:
    try:
        genai.configure(api_key=GOOGLE_API_KEY)
    except Exception as e:
        logger.error(f"Gemini APIキーの設定中にエラーが発生しました: {e}")
        GOOGLE_API_KEY = None # エラー時はキーを無効化

# Geminiモデルの初期化 (エラーハンドリング追加)
gemini_model = None
if GOOGLE_API_KEY:
    try:
        gemini_model = genai.GenerativeModel('gemini-1.5-flash') # または 'gemini-pro'
    except Exception as e:
        logger.error(f"Geminiモデルの初期化中にエラー: {e}")
        gemini_model = None


SYSTEM_PROMPT_JSON_FORMAT_GUIDANCE = """
抽出情報 (extractedInfo) は、必ず以下のJSON形式で、キーの抜け漏れなく、かつ余計なキーを含めずに出力してください。
情報がまだ得られていない項目は `null` としてください。
ヒアリングが完了したと判断できるまで `isComplete` は `false` にしてください。
ユーザーへの返答である `aiResponse` には、決してJSON形式の文字列や、`extractedInfo` のキー名（例: "purposeAndWork"）、その値、`null` といったプログラミング上の表現を含めず、純粋にユーザーフレンドリーな会話文のみを生成してください。ヒアリングで得られた情報をユーザーに確認のために要約して提示する場合も、自然な文章で行ってください。
ヒアリング完了時には、これまでのヒアリング内容全体を要約し、以下の `extractedInfo` に含まれる全ての項目（特に `deviceName`, `overview` なども）を可能な限り具体的に埋めてください。
{
    "purposeAndWork": "<抽出された目的とワーク>",
    "taktAndAutomation": "<抽出されたタクトタイムと自動化レベル>",
    "mainProcess": "<抽出された主要加工や検査内容>",
    "environmentAndUtilities": "<抽出された設置環境とユーティリティ>",
    "issuesAndBudget": "<抽出された課題と予算感>",
    "isComplete": false,
    "deviceName": "<提案する設備名称（仮称。例：AI提案型 自動〇〇装置）>",
    "overview": "<提案する設備の概要（上記5項目を元に簡潔にまとめる）>",
    "mainFunctions": ["<主要機能1>", "<主要機能2>", "<主要機能3>", "..."],
    "environment": ["<設置環境・ユーティリティに関する記述1>", "<記述2>", "..."],
    "expectations": "<顧客の期待や課題の要約>",
    "budget": "<顧客が提示したおおよその予算感>"
}
"""

# result.htmlが表示に使う情報をDEFAULT_EXTRACTED_INFOにも追加（ただし通常はnull）
DEFAULT_RESULT_INFO_KEYS = {
    "deviceName": None,
    "overview": None,
    "mainFunctions": [], # リストなので空リスト
    "environment": [],   # リストなので空リスト
    "expectations": None,
    "budget": None
}


SYSTEM_PROMPT = f"""
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
- **重要:** あなたの応答は、必ず指定されたJSON形式に従ってください。このJSONオブジェクトは、キーとして `aiResponse` と `extractedInfo` を持ちます。
    - `aiResponse` キーの値は、ユーザーに表示するための自然な会話文（文字列）**のみ**にしてください。この会話文には、JSONオブジェクトの文字列や `extractedInfo` のキー名、`null`のような値をそのままの形で決して含めないでください。
    - `extractedInfo` キーの値は、ヒアリングで得られた情報を格納するJSONオブジェクトです。{SYSTEM_PROMPT_JSON_FORMAT_GUIDANCE}で指示された通りのキーと値の構造にしてください。
- 上記5つの主要項目 (目的とワーク, 生産量と自動化レベル, 主要加工と機能, 設置環境とユーティリティ, 現状課題と予算感) について、ユーザーから十分な情報を得られたとあなたが判断した場合、`extractedInfo` 内の `isComplete` を `true` に設定してください。その際、`aiResponse` でヒアリングが完了したことをユーザーに自然な会話で伝え、提案書を確認するよう促してください。
- ユーザーが明確に「完了」「終わり」「もう十分です」などとヒアリングの終了を望む発言をした場合は、それまでのヒアリング内容で提案書を作成する試みとして、`extractedInfo` 内の `isComplete` を `true` に設定してください。もし情報が不足していると感じる場合でも、その旨を `aiResponse` で（例えば「承知いたしました。では、これまでの情報で提案を作成しますね。もしよろしければ、〇〇についてもう少し詳しくお伺いできると、より詳細な提案が可能です。」のように）丁寧に伝えつつ、`isComplete: true` として処理を完了させてください。

さあ、最初の挨拶をして、ユーザーにどのような設備を検討しているか尋ねてください。
"""

DEFAULT_EXTRACTED_INFO = {
    "purposeAndWork": None,
    "taktAndAutomation": None,
    "mainProcess": None,
    "environmentAndUtilities": None,
    "issuesAndBudget": None,
    "isComplete": False,
    **DEFAULT_RESULT_INFO_KEYS # result.html向けのキーもデフォルトに含める
}

# @app.before_first_request # Flask 2.x以降では廃止
def initial_database_setup():
    """アプリケーションの最初のリクエストの前にデータベースを初期化します。"""
    # この関数はアプリケーションコンテキスト内で呼び出す必要がある
    logger.info("アプリケーション初回起動時のデータベース初期化処理を開始します。")
    try:
        # 環境変数のチェック
        if not all([db_utils.DB_USER, db_utils.DB_PASSWORD, db_utils.DB_NAME]):
            logger.error("データベース接続情報（ユーザー名、パスワード、データベース名）が.envファイルに正しく設定されていません。")
            return

        # 接続テストと初期化
        conn_test = db_utils.get_db_connection()
        logger.info(f"データベース ({db_utils.DB_NAME} on {db_utils.DB_HOST}:{db_utils.DB_PORT}) 接続テスト成功。")
        conn_test.close()
        db_utils.initialize_db()
        logger.info("データベースの初期化処理が完了しました。")
    except Exception as e:
        logger.error(f"データベース初期化中に致命的なエラーが発生しました: {e}", exc_info=True)

# アプリケーションの初期化時にデータベースセットアップを実行
# Flaskアプリケーションのインスタンスが作成された後、かつ最初のリクエスト処理前 (のようなタイミング)
# 実際には、`app.run()` の前や、アプリケーションファクトリパターンを使っている場合はその中で行う。
# ここでは、`app`インスタンス作成後にコンテキストを作って呼び出す。
with app.app_context():
    initial_database_setup()

# HTMLファイルを提供するためのルート
from flask import send_from_directory

@app.route('/')
def index_route(): # 関数名を index から index_route に変更 (Pythonの予約語と衝突する可能性を避ける)
    return send_from_directory('.', 'index.html')

@app.route('/<path:filename>')
def serve_html(filename):
    # hearing.html, result.html, thankyou.html, index.html を提供
    # index.html はルートでも提供されるが、直接 /index.html でもアクセス可能にする
    allowed_files = ['hearing.html', 'result.html', 'thankyou.html', 'index.html']
    if filename in allowed_files:
        return send_from_directory('.', filename)
    # Faviconなどの一般的なリクエストに対しては404を返す
    if filename == 'favicon.ico':
        return jsonify({"error": "File not found"}), 404

    # それ以外の不明なファイルリクエストも404
    logger.warning(f"Unknown file requested: {filename}")
    return jsonify({"error": "File not found"}), 404


@app.route('/api/chat', methods=['POST'])
def chat_handler():
    global gemini_model
    if not GOOGLE_API_KEY or not gemini_model:
        logger.error("Gemini APIキー未設定またはモデル初期化失敗のため、API呼び出し不可。")
        return jsonify({"error": "Gemini APIが設定されていないか、モデルの初期化に失敗しました。"}), 500

    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Invalid JSON payload"}), 400

        user_message_text = data.get('message')
        session_id_from_request = data.get('sessionId') # フロントから送られてくるセッションID

        if not user_message_text:
            return jsonify({"error": "message is required"}), 400

        # セッションIDの管理
        current_session_id = session_id_from_request
        if not current_session_id:
            # 新規セッションの場合、DBにセッションレコードを作成
            current_session_id = db_utils.create_chat_session()
            if not current_session_id:
                logger.error("新規チャットセッションの作成に失敗しました。")
                return jsonify({"error": "Failed to create a new chat session."}), 500
            logger.info(f"新規チャットセッションID: {current_session_id} を作成しました。")
        else:
            logger.info(f"既存のチャットセッションID: {current_session_id} を使用します。")


        # フロントエンドから送られてくる会話履歴 (currentSessionHistory) をGeminiの履歴形式に変換
        session_history_frontend = data.get('currentSessionHistory', [])
        gemini_history = []
        for entry in session_history_frontend:
            role = entry.get('role')
            text_parts = entry.get('parts', [])
            if role and text_parts and isinstance(text_parts, list) and len(text_parts) > 0:
                 text = text_parts[0].get('text', '')
                 if text:
                    gemini_history.append({'role': role, 'parts': [{'text': text}]})

        # DBから最新のextractedInfoを取得（セッション継続時のため）
        # ただし、Geminiに渡すのはフロントの履歴に任せ、DBのextractedInfoは応答後に更新する
        # last_extracted_info_db = db_utils.get_latest_extracted_information(current_session_id)
        # current_extracted_info = DEFAULT_EXTRACTED_INFO.copy()
        # if last_extracted_info_db:
        #     for key in current_extracted_info:
        #         if key in last_extracted_info_db and last_extracted_info_db[key] is not None:
        #             current_extracted_info[key] = last_extracted_info_db[key]


        # Gemini API呼び出し (リクエスト内容を保存するために、ここでリクエストオブジェクトを構築)
        gemini_request_payload = {
            "contents": gemini_history + [{'role': 'user', 'parts': [{'text': user_message_text}]}],
            # generation_config, safety_settings なども必要に応じて追加
        }

        model_with_system_prompt = genai.GenerativeModel(
            'gemini-1.5-flash',
            system_instruction=SYSTEM_PROMPT
        )
        chat = model_with_system_prompt.start_chat(history=gemini_history if gemini_history else None)

        logger.debug(f"Session {current_session_id}: Sending to Gemini: user_message='{user_message_text}', history_length={len(gemini_history)}")
        response = chat.send_message(user_message_text)
        gemini_response_text = response.text
        logger.debug(f"Session {current_session_id}: Gemini raw response: {gemini_response_text[:500]}...") # 長すぎる場合があるので一部表示

        # ユーザーメッセージをDBに保存
        db_utils.add_chat_log(current_session_id, "user", user_message_text, raw_request=gemini_request_payload)

        ai_response_text = "AIからの応答を処理できませんでした。" # デフォルト
        extracted_info = DEFAULT_EXTRACTED_INFO.copy() # デフォルト

        try:
            cleaned_response_text = gemini_response_text.strip()
            if cleaned_response_text.startswith("```json"):
                cleaned_response_text = cleaned_response_text[len("```json"):]
            if cleaned_response_text.endswith("```"):
                cleaned_response_text = cleaned_response_text[:-len("```")]

            gemini_output = json.loads(cleaned_response_text)
            ai_response_text = gemini_output.get("aiResponse", f"AIからの応答形式が不正です: {gemini_response_text[:100]}")

            temp_extracted_info = gemini_output.get("extractedInfo", {})
            # キーの存在と型をチェックしてextracted_infoを構築
            for key in DEFAULT_EXTRACTED_INFO:
                if key in temp_extracted_info and isinstance(temp_extracted_info[key], type(DEFAULT_EXTRACTED_INFO[key])):
                    extracted_info[key] = temp_extracted_info[key]
                elif key == "isComplete" and key in temp_extracted_info and isinstance(temp_extracted_info[key], bool): # isCompleteはbool
                     extracted_info[key] = temp_extracted_info[key]


        except json.JSONDecodeError as je:
            logger.error(f"Session {current_session_id}: Gemini response JSONDecodeError: {je}. Response text: {gemini_response_text}")
            ai_response_text = gemini_response_text
            # extracted_info は DEFAULT_EXTRACTED_INFO のまま
            if "完了" in user_message_text.lower() or "おわり" in user_message_text.lower() or "終わり" in user_message_text.lower():
                # ユーザーが完了と言ったが、AIがJSONを返さなかった場合、既存のDB情報でisCompleteを判定する試み
                db_info = db_utils.get_latest_extracted_information(current_session_id)
                if db_info and all(db_info.get(k) for k in ["purpose_and_work", "takt_and_automation", "main_process_and_functions", "environment_and_utilities", "issues_and_budget"]):
                    extracted_info["isComplete"] = True
                else:
                    ai_response_text += "\n\n恐れ入りますが、まだ全ての項目についてお伺いできていないようです。ヒアリングを続けてもよろしいでしょうか？"
                    extracted_info["isComplete"] = False
        except Exception as e:
            logger.error(f"Session {current_session_id}: Error processing Gemini response: {e}. Response text: {gemini_response_text}", exc_info=True)
            # extracted_info は DEFAULT_EXTRACTED_INFO のまま

        # AIの応答と抽出情報をDBに保存
        db_utils.add_chat_log(current_session_id, "ai", ai_response_text, raw_response={"text": gemini_response_text})
        db_utils.upsert_extracted_information(current_session_id, extracted_info)

        if extracted_info.get("isComplete"):
            logger.info(f"Session {current_session_id}: ヒアリング完了。セッション概要を更新します。")
            db_utils.update_chat_session_summary(current_session_id, extracted_info, True)

        response_data = {
            "sessionId": current_session_id, # フロントにセッションIDを返す
            "aiResponse": ai_response_text,
            "extractedInfo": extracted_info
        }
        return jsonify(response_data)

    except Exception as e:
        logger.error(f"Error in /api/chat (Session: {data.get('sessionId', 'N/A')}): {e}", exc_info=True)
        return jsonify({"error": "サーバー内部エラーが発生しました。"}), 500

@app.route('/api/contact', methods=['POST'])
def contact_submit():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Invalid JSON payload"}), 400

        name = data.get('name')
        company_name = data.get('companyName')
        email = data.get('email')
        phone_number = data.get('phoneNumber')
        # session_id は、お問い合わせフォーム送信時にチャットセッションと紐付ける場合に利用
        # result.html から送られてくる localstorage の chatSummary に sessionId が含まれている想定
        # chatSummary = data.get('chatSummary', {})
        # session_id_to_link = chatSummary.get('sessionId') # もしchatSummary内にsessionIdがあれば

        # 必須項目のバリデーション (例: 氏名とメールアドレス)
        if not name or not email:
            return jsonify({"error": "Name and email are required."}), 400

        # どのチャットセッションと紐づけるか？
        # 案1: /api/contact リクエスト時に sessionId も送ってもらう
        #      (result.html のフォーム送信JSで、localStorageからsessionIdも取得して送信)
        session_id_to_link = data.get('sessionId') # フロントから sessionId が送られてくると仮定

        user_id = db_utils.add_user(name, company_name, email, phone_number, session_id_to_link=session_id_to_link)

        if user_id:
            logger.info(f"お問い合わせフォームからユーザー情報が保存されました。User ID: {user_id}, Email: {email}")
            # 成功したらサンキューページへリダイレクトすることをフロントエンドに期待する
            # ここでは成功した旨のJSONを返す
            return jsonify({"message": "Contact information received successfully.", "userId": user_id}), 201
        else:
            logger.error(f"お問い合わせフォームのユーザー情報保存に失敗しました。Email: {email}")
            return jsonify({"error": "Failed to save contact information."}), 500

    except Exception as e:
        logger.error(f"Error in /api/contact: {e}", exc_info=True)
        return jsonify({"error": "サーバー内部エラーが発生しました。"}), 500


if __name__ == '__main__':
    logger.info("アプリケーションを開発モードで起動します。")
    # app.before_first_requestでDB初期化が実行される
    app.run(debug=True, port=5000)
