# AI設備仕様コンシェルジュ バックエンド 環境構築ガイド

このドキュメントは、「AI設備仕様コンシェルジュ」アプリケーションのバックエンド環境をセットアップするための手順を説明します。

## 1. 前提条件

*   Python 3.8 以上
*   PostgreSQL データベースサーバーが利用可能であること
*   Git (ソースコードの取得に必要)
*   Google Gemini API キー

## 2. 環境構築手順

### 2.1. リポジトリのクローン（またはファイルの配置）

Gitリポジトリからソースコードをクローンします。
（リポジトリがまだ存在しない場合は、提供されたソースコードファイル一式を任意のディレクトリに配置してください。）

```bash
# git clone <リポジトリURL>
# cd <リポジトリ名>
```

### 2.2. Python仮想環境の作成と有効化

プロジェクトルートでPythonの仮想環境を作成し、有効化します。

```bash
# Windows
python -m venv venv
.\venv\Scripts\activate

# macOS / Linux
python3 -m venv venv
source venv/bin/activate
```

### 2.3. 必要なライブラリのインストール

`requirements.txt` ファイルを使用して、必要なPythonライブラリをインストールします。

```bash
pip install -r requirements.txt
```

### 2.4. 環境変数の設定

プロジェクトルートに `.env` という名前のファイルを作成し、以下の内容を記述します。
実際の値に置き換えてください。

```env
# Gemini API Key
GOOGLE_API_KEY="YOUR_GEMINI_API_KEY_HERE"

# PostgreSQL Database Connection URL
# 例: postgresql://your_db_user:your_db_password@your_db_host:your_db_port/your_db_name
DATABASE_URL="postgresql://user:password@host:port/database"
```

**注意:**
*   `YOUR_GEMINI_API_KEY_HERE` を実際のGoogle Gemini APIキーに置き換えてください。
*   `DATABASE_URL` を実際のPostgreSQL接続文字列に置き換えてください。
    *   ユーザー名、パスワード、ホスト、ポート、データベース名を環境に合わせて設定します。
    *   例: `postgresql://postgres:mypassword@localhost:5432/ai_concierge_db`

### 2.5. データベースの初期化

PostgreSQLサーバーが起動していることを確認し、以下のコマンドを実行してデータベーステーブルを作成します。

```bash
python init_db.py
```

成功すると、各テーブルが作成された旨のメッセージが表示されます。

## 3. アプリケーションの起動

### 3.1. バックエンドAPIサーバーの起動

以下のコマンドでFlask開発サーバーを起動します。

```bash
python app.py
```

デフォルトでは、APIサーバーは `http://localhost:5000` で起動します。
コンソールに `* Running on http://127.0.0.1:5000` のようなメッセージが表示されれば成功です。

### 3.2. フロントエンドの表示

ウェブブラウザで以下のいずれかのHTMLファイルを開きます。
通常は `index.html` から開始します。

*   `index.html` (トップページ)
*   `hearing.html` (チャットインターフェース)

これらのファイルは、ローカルファイルシステムから直接ブラウザで開くことができます（例: `file:///path/to/your/project/index.html`）。

## 4. 動作確認

1.  ブラウザで `index.html` を開き、「今すぐ無料診断を始める！」ボタンをクリックして `hearing.html` に遷移します。
2.  チャットUIでAIとの会話を開始します。
    *   バックエンドのコンソールログにリクエストやAIの応答に関するログが出力されることを確認します。
    *   データベースの `ChatSessions`, `ChatLogs`, `ExtractedInformation` テーブルにデータが記録されることを確認します。
3.  AIがヒアリング完了と判断すると、自動的に `result.html`（簡易提案書ページ）に遷移します。
    *   `localStorage` に `aiChatSummary` が保存されていることを確認します。
    *   提案書の内容がチャット内容に基づいて表示されることを確認します。
4.  `result.html` の「詳細ヒアリングお申し込みフォーム」に情報を入力し、送信します。
    *   バックエンドの `/api/contact` が呼び出され、データベースの `Users` テーブルに情報が保存され、関連する `ChatSessions` の `user_id` が更新されることを確認します。
    *   成功すると `thankyou.html` に遷移します。

## 5. トラブルシューティング

*   **`GOOGLE_API_KEY is not set` / `DATABASE_URL is not set`**: `.env` ファイルが正しく設定されているか確認してください。
*   **データベース接続エラー**: `DATABASE_URL` の設定内容（ユーザー名、パスワード、ホスト、ポート、データベース名）が正しいか、PostgreSQLサーバーが起動しているか確認してください。
*   **APIエラー**: バックエンドのコンソールログやブラウザの開発者ツールコンソールでエラーメッセージを確認してください。Gemini APIキーの権限や残高なども確認点です。
*   **フロントエンドが正しく動作しない**: ブラウザの開発者ツールコンソールでJavaScriptのエラーを確認してください。APIのURL (`http://localhost:5000`) が正しいかなども確認点です。

以上で環境構築とアプリケーションの起動は完了です。
```
