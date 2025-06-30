## 開発原則
1.フロントエンド担当AIとバックエンド担当AIにて開発を行う
2.ユーザーは確認のみを行い、確認手順はドキュメントで指示すること
3.フロントエンド担当とバックエンド担当お互いが相手側コードのチェックを行う事
4.優先事項で迷う場合はユーザーに問うこと

## バックエンド開発について

### 必要なもの
- Python 3.8以上
- PostgreSQL データベース

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
     - `GOOGLE_API_KEY`: あなたのGoogle Gemini APIキーを設定してください。
     - `DB_HOST`: PostgreSQLデータベースのホスト名 (デフォルト: `localhost`)
     - `DB_PORT`: PostgreSQLデータベースのポート (デフォルト: `5432`)
     - `DB_NAME`: 使用するデータベース名 (例: `ai_concierge_db`)
     - `DB_USER`: データベースのユーザー名
     - `DB_PASSWORD`: データベースのパスワード
     **注意:** `.env` ファイルはGit管理に含めないでください (`.gitignore` に追加推奨)。

5. **データベースの準備:**
   - 設定した `DB_NAME` でPostgreSQLデータベースが作成されていることを確認してください。
   - 必要なテーブルは、初回起動時に自動的に作成されるか、別途マイグレーションスクリプトが必要になる場合があります（開発初期は `app.py` 内で作成を試みます）。

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