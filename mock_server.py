from flask import Flask, request, jsonify
from flask_cors import CORS # クロスオリジンリクエストを許可するために必要
import random
import time

app = Flask(__name__)
CORS(app) # すべてのオリジンからのリクエストを許可 (開発用)

# hearing.html の getDummyApiResponse に相当するロジック
def get_dummy_api_response_for_python(user_message, history):
    ai_response = f"Pythonサーバーからの応答です。「{user_message}」についてですね。"
    # 簡単な会話履歴の参照（実際のAIよりずっと単純）
    current_purpose = None
    current_takt = None
    # 簡易的な履歴のキーワードチェックで状態を把握しようと試みる
    # より堅牢にするには、ユーザーの直前の回答を解析する必要がある
    if history:
        for entry in reversed(history):
            if entry['role'] == 'model':
                text = entry['parts'][0]['text']
                if "目的とワーク" in text:
                    # このAIの質問の後にユーザーが答えたはずなので、その一つ前がユーザーの回答
                    user_reply_index = history.index(entry) -1
                    if user_reply_index >= 0 and history[user_reply_index]['role'] == 'user':
                         current_purpose = history[user_reply_index]['parts'][0]['text']
                    break # 目的が見つかったらループを抜ける
        for entry in reversed(history):
            if entry['role'] == 'model':
                text = entry['parts'][0]['text']
                if "タクトと自動化" in text:
                    user_reply_index = history.index(entry) -1
                    if user_reply_index >= 0 and history[user_reply_index]['role'] == 'user':
                        current_takt = history[user_reply_index]['parts'][0]['text']
                    break

    extracted_info = {
        "purposeAndWork": current_purpose,
        "taktAndAutomation": current_takt,
        "mainProcess": None,
        "environmentAndUtilities": None,
        "issuesAndBudget": None,
        "isComplete": False
    }

    if user_message.lower() in ["完了", "終わり", "おわり"]:
        ai_response = "Pythonサーバーより: ヒアリングのご協力ありがとうございました。全ての情報が揃いましたので、簡易提案書を作成します。"
        extracted_info["isComplete"] = True
        extracted_info["purposeAndWork"] = extracted_info["purposeAndWork"] or "〇〇部品の組立 (Python)"
        extracted_info["taktAndAutomation"] = extracted_info["taktAndAutomation"] or "全自動でタクト10秒 (Python)"
        extracted_info["mainProcess"] = "主要加工はプレス、重要機能は画像検査 (Python)"
        extracted_info["environmentAndUtilities"] = "一般工場、電源AC200V、エア圧0.5MPa (Python)"
        extracted_info["issuesAndBudget"] = "課題は生産性向上、予算500万円 (Python)"
        extracted_info["deviceName"] = "AI提案型 自動組立機 (Py-Mock)"
        extracted_info["overview"] = f"ユーザー様との対話に基づき、{extracted_info['purposeAndWork']}を目的とし、{extracted_info['taktAndAutomation']}を目指す設備を提案します。 (Py-Mock)"
        extracted_info["mainFunctions"] = [extracted_info["mainProcess"], "自動部品供給 (Py)", "完成品自動排出 (Py)"]
        extracted_info["environment"] = [extracted_info["environmentAndUtilities"]]
        extracted_info["expectations"] = extracted_info["issuesAndBudget"]
        extracted_info["budget"] = "500万円 (Py-Mock)"
    elif not current_purpose and ("組立" in user_message or "検査" in user_message or "自動化" in user_message):
        ai_response += "\nまず、この設備で実現したい「目的」と、扱いたい「ワーク（製品）」について具体的に教えていただけますか？ (例: 基板への部品実装、金属部品の外観検査など) (Py)"
    elif current_purpose and not current_takt:
        ai_response += "\nありがとうございます。次に、目標とする「生産量（例：1時間あたり何個）」または「タクトタイム（1つあたり何秒）」と、ご希望の「自動化レベル（全自動、半自動、手動など）」を教えてください。 (Py)"
    # ... (他の質問ステップも同様に追加可能) ...
    else:
        ai_response += "\n他に何か補足事項やご要望はございますか？なければ「完了」と入力してください。 (Py)"
    
    return {"aiResponse": ai_response, "extractedInfo": extracted_info}

@app.route('/api/chat', methods=['POST'])
def chat_handler():
    data = request.json
    user_message = data.get('message')
    # フロントから送られてくる currentSessionHistory は、今回のユーザー発言を含まない、それ以前の履歴のはず
    session_history_from_client = data.get('currentSessionHistory', []) 
    
    # サーバー側で今回のユーザー発言を履歴に追加してダミーAIに渡す
    current_complete_history = list(session_history_from_client) # コピーを作成
    current_complete_history.append({'role': 'user', 'parts': [{'text': user_message}]})

    print(f"受信メッセージ: {user_message}")
    # print(f"クライアントからの履歴: {session_history_from_client}")
    # print(f"ダミーAIに渡す完全な履歴: {current_complete_history}")

    time.sleep(random.uniform(0.5, 1.5))
    
    response_data = get_dummy_api_response_for_python(user_message, current_complete_history)
    
    print(f"送信レスポンス: {response_data['aiResponse']}")
    return jsonify(response_data)

if __name__ == '__main__':
    app.run(debug=True, port=5000)