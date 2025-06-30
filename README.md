## 開発原則
1.フロントエンド担当AIとバックエンド担当AIにて開発を行う
2.ユーザーは確認のみを行い、確認手順はドキュメントで指示すること
3.フロントエンド担当とバックエンド担当お互いが相手側コードのチェックを行う事
4.優先事項で迷う場合はユーザーに問うこと

## バックエンド開発について

### 必要なもの
- Python 3.8以上
- MySQL データベース (バージョン 5.7 以降推奨)

### セットアップ手順
1. **リポジトリのクローン:**
   ```bash
   git clone <リポジトリURL>
   cd <リポジトリ名>
   ```
2. **Python仮想環境の作成と有効化:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # Linux/macOSの場合
   # venv\Scripts\activate    # Windowsの場合
   ```
   既に `venv` ディレクトリが存在する場合は、有効化のみ行います。

3. **必要なライブラリのインストール:**
   ```bash
   pip install -r requirements.txt
   ```
4. **環境変数の設定:**
   - `.env.example` ファイルを参考に `.env` ファイルを作成（またはコピーしてリネーム）します。
     ```bash
     cp .env.example .env # .env.example があれば
     ```
     もし `.env.example` がなければ、手動で `.env` ファイルをプロジェクトルートに作成してください。
   - `.env` ファイルを開き、以下の情報を設定します。
     - `FLASK_SECRET_KEY`: Flaskセッション管理用の任意の秘密鍵 (例: `your_very_secret_flask_key`)
     - `GOOGLE_API_KEY`: あなたのGoogle Gemini APIキーを設定してください。
     - `DB_HOST`: MySQLデータベースのホスト名 (デフォルト: `localhost`)
     - `DB_PORT`: MySQLデータベースのポート (デフォルト: `3306`)
     - `DB_NAME`: 使用するデータベース名 (例: `ai_concierge_db`)
     - `DB_USER`: MySQLデータベースのユーザー名
     - `DB_PASSWORD`: MySQLデータベースのパスワード
     **注意:** `.env` ファイルはGit管理に含めないでください (`.gitignore` に追加推奨)。

   参考となる `.env` ファイルの例:
   ```env
   FLASK_SECRET_KEY="your_random_secret_key_here"
   GOOGLE_API_KEY="YOUR_GEMINI_API_KEY_HERE"
   DB_HOST="localhost"
   DB_PORT="3306"
   DB_NAME="ai_concierge_db"
   DB_USER="your_mysql_user"
   DB_PASSWORD="your_mysql_password"
   ```

5. **データベースの準備:**
   - 設定した `DB_NAME` でMySQLデータベースが作成されており、`DB_USER` がそのデータベースへの適切な権限を持っていることを確認してください。
   - 文字コードは `utf8mb4` を推奨します。
   - 必要なテーブルは、アプリケーションの初回起動時に自動的に作成されるように実装されています (`app.py`内の`initial_database_setup`関数経由)。

### 開発サーバーの実行
開発時には、以下のコマンドでFlask開発サーバーを起動できます。
```bash
python app.py
```
サーバーは `http://localhost:5000` で起動します。
`hearing.html` はこのアドレスの `/api/chat` エンドポイントを呼び出すように設定されています。

### 本番環境へのデプロイ (Gunicornを使用する場合)
Gunicorn を使用してアプリケーションをデプロイする場合のコマンド例です。
```bash
gunicorn --bind 0.0.0.0:5000 app:app
```
実際には、ワーカー数やログ設定など、環境に合わせて調整してください。