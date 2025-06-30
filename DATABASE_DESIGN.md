# AI設備仕様コンシェルジュ データベース設計

## 1. 概要

本文書は、「AI設備仕様コンシェルジュ」アプリケーションのバックエンドで使用されるPostgreSQLデータベースの設計について記述します。
データベースは、ユーザー情報、AIとのチャットセッション、会話ログ、およびAIによって抽出された仕様情報を格納します。

## 2. テーブル定義

以下に各テーブルの定義を示します。

### 2.1. Users (顧客情報)

顧客（お問い合わせフォーム送信者）の情報を格納します。

| カラム名         | データ型                        | 制約                                  | 説明                                     |
| ---------------- | ------------------------------- | ------------------------------------- | ---------------------------------------- |
| `user_id`        | `SERIAL`                        | `PRIMARY KEY`                         | ユーザーID (自動採番)                      |
| `name`           | `VARCHAR(255)`                  |                                       | 氏名                                     |
| `company_name`   | `VARCHAR(255)`                  |                                       | 会社名                                   |
| `email`          | `VARCHAR(255)`                  | `UNIQUE`                              | メールアドレス                           |
| `phone_number`   | `VARCHAR(50)`                   |                                       | 電話番号 (任意)                          |
| `created_at`     | `TIMESTAMP WITH TIME ZONE`      | `DEFAULT CURRENT_TIMESTAMP`           | 作成日時                                 |

**SQL定義 (init_db.pyより):**
```sql
CREATE TABLE IF NOT EXISTS Users (
    user_id SERIAL PRIMARY KEY,
    name VARCHAR(255),
    company_name VARCHAR(255),
    email VARCHAR(255) UNIQUE,
    phone_number VARCHAR(50),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

### 2.2. ChatSessions (チャットセッション情報)

AIとの一連の会話セッション情報を格納します。

| カラム名                   | データ型                        | 制約                                  | 説明                                                                 |
| -------------------------- | ------------------------------- | ------------------------------------- | -------------------------------------------------------------------- |
| `session_id`               | `UUID`                          | `PRIMARY KEY`                         | セッションID (UUID)                                                    |
| `user_id`                  | `INTEGER`                       | `REFERENCES Users(user_id) ON DELETE SET NULL` | ユーザーID (Usersテーブルへの外部キー、ユーザー削除時はNULLに設定)         |
| `start_time`               | `TIMESTAMP WITH TIME ZONE`      | `DEFAULT CURRENT_TIMESTAMP`           | セッション開始日時                                                       |
| `end_time`                 | `TIMESTAMP WITH TIME ZONE`      |                                       | セッション終了日時 (ヒアリング完了時)                                    |
| `final_proposal_summary`   | `JSONB`                         |                                       | 最終的な提案概要 (ヒアリング完了時のExtractedInformationに基づくJSON) |
| `created_at`               | `TIMESTAMP WITH TIME ZONE`      | `DEFAULT CURRENT_TIMESTAMP`           | 作成日時                                                             |
| `updated_at`               | `TIMESTAMP WITH TIME ZONE`      | `DEFAULT CURRENT_TIMESTAMP`           | 更新日時 (トリガーにより自動更新)                                        |

**SQL定義 (init_db.pyより):**
```sql
CREATE TABLE IF NOT EXISTS ChatSessions (
    session_id UUID PRIMARY KEY,
    user_id INTEGER REFERENCES Users(user_id) ON DELETE SET NULL,
    start_time TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    end_time TIMESTAMP WITH TIME ZONE,
    final_proposal_summary JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```
**補足:**
* `updated_at` は後述のトリガーによって自動更新されます。

### 2.3. ChatLogs (会話ログ)

個々のチャットメッセージ（ユーザーの発言とAIの応答）を時系列で格納します。

| カラム名                 | データ型                        | 制約                                                          | 説明                                                                 |
| ------------------------ | ------------------------------- | ------------------------------------------------------------- | -------------------------------------------------------------------- |
| `log_id`                 | `SERIAL`                        | `PRIMARY KEY`                                                 | ログID (自動採番)                                                      |
| `session_id`             | `UUID`                          | `REFERENCES ChatSessions(session_id) ON DELETE CASCADE NOT NULL` | セッションID (ChatSessionsテーブルへの外部キー、セッション削除時はCASCADE削除) |
| `sender`                 | `VARCHAR(10)`                   | `NOT NULL CHECK (sender IN ('user', 'ai'))`                  | 送信者 ("user" または "ai")                                            |
| `message_content`        | `TEXT`                          | `NOT NULL`                                                    | メッセージ内容                                                         |
| `timestamp`              | `TIMESTAMP WITH TIME ZONE`      | `DEFAULT CURRENT_TIMESTAMP`                                   | メッセージ送信日時                                                       |
| `raw_gemini_request`     | `JSONB`                         |                                                               | (デバッグ用) Gemini APIへのリクエスト内容                              |
| `raw_gemini_response`    | `JSONB`                         |                                                               | (デバッグ用) Gemini APIからのレスポンス内容                            |

**SQL定義 (init_db.pyより):**
```sql
CREATE TABLE IF NOT EXISTS ChatLogs (
    log_id SERIAL PRIMARY KEY,
    session_id UUID REFERENCES ChatSessions(session_id) ON DELETE CASCADE NOT NULL,
    sender VARCHAR(10) NOT NULL CHECK (sender IN ('user', 'ai')), -- 'user' or 'ai'
    message_content TEXT NOT NULL,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    raw_gemini_request JSONB, -- For debugging
    raw_gemini_response JSONB -- For debugging
);
```

### 2.4. ExtractedInformation (抽出情報)

AIが会話から抽出した構造化された情報を格納します。会話の進行に伴い、スナップショットとして複数レコードが同一セッションに対して保存される可能性があります。

| カラム名                        | データ型                        | 制約                                                          | 説明                                                              |
| ------------------------------- | ------------------------------- | ------------------------------------------------------------- | ----------------------------------------------------------------- |
| `info_id`                       | `SERIAL`                        | `PRIMARY KEY`                                                 | 情報ID (自動採番)                                                   |
| `session_id`                    | `UUID`                          | `REFERENCES ChatSessions(session_id) ON DELETE CASCADE NOT NULL` | セッションID (ChatSessionsテーブルへの外部キー、セッション削除時はCASCADE削除) |
| `purpose_and_work`              | `TEXT`                          |                                                               | 抽出された目的とワーク                                                |
| `takt_and_automation`           | `TEXT`                          |                                                               | 抽出されたタクトタイムと自動化レベル                                    |
| `main_process_and_functions`    | `TEXT`                          |                                                               | 抽出された主要加工や検査内容、重要な機能                                |
| `environment_and_utilities`     | `TEXT`                          |                                                               | 抽出された設置環境とユーティリティ                                    |
| `issues_and_budget`             | `TEXT`                          |                                                               | 抽出された課題と予算感                                                |
| `is_complete`                   | `BOOLEAN`                       | `DEFAULT FALSE`                                               | ヒアリングが完了したかどうかのフラグ                                    |
| `raw_extracted_info`            | `JSONB`                         |                                                               | AIから返却された抽出情報の生JSON（デバッグ・分析用）                      |
| `created_at`                    | `TIMESTAMP WITH TIME ZONE`      | `DEFAULT CURRENT_TIMESTAMP`                                   | 作成日時                                                          |
| `updated_at`                    | `TIMESTAMP WITH TIME ZONE`      | `DEFAULT CURRENT_TIMESTAMP`                                   | 更新日時 (トリガーにより自動更新)                                     |

**SQL定義 (init_db.pyより):**
```sql
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
```
**補足:**
*   このテーブルは、AIが情報を抽出・更新するたびに新しいレコードが追加されるか、既存のレコードが更新される形でスナップショットが記録されることを想定しています。アプリケーションロジックで、特定のセッションに対する最新の `ExtractedInformation` を取得する際は、`updated_at` または `created_at` で降順ソートして最初のレコードを取得するなどの対応が必要です。
*   `is_complete` が `true` になった時点のレコードが、そのセッションにおける最終的なヒアリング結果となります。この内容は、`ChatSessions.final_proposal_summary` にも集約して格納されることが期待されます。
*   `updated_at` は後述のトリガーによって自動更新されます。

## 3. リレーションシップ

主要なテーブル間のリレーションシップは以下の通りです。

*   **`Users` と `ChatSessions`**:
    *   `ChatSessions.user_id` は `Users.user_id` を参照します (一対多、Users側が「一」)。
    *   ユーザーが問い合わせフォームを送信するまでは `ChatSessions.user_id` は `NULL` となります。フォーム送信後に紐付けられます。
    *   ユーザーが削除された場合、関連するチャットセッションの `user_id` は `NULL` に設定されます (`ON DELETE SET NULL`)。チャットセッション自体は残ります。

*   **`ChatSessions` と `ChatLogs`**:
    *   `ChatLogs.session_id` は `ChatSessions.session_id` を参照します (一対多、ChatSessions側が「一」)。
    *   チャットセッションが削除された場合、関連する会話ログもすべて削除されます (`ON DELETE CASCADE`)。

*   **`ChatSessions` と `ExtractedInformation`**:
    *   `ExtractedInformation.session_id` は `ChatSessions.session_id` を参照します (一対多、ChatSessions側が「一」)。
    *   チャットセッションが削除された場合、関連する抽出情報もすべて削除されます (`ON DELETE CASCADE`)。

ER図の代わりにテキストで表現すると以下のようになります:

```
Users (1) ---- (0..*) ChatSessions

ChatSessions (1) ---- (0..*) ChatLogs
ChatSessions (1) ---- (0..*) ExtractedInformation
```

## 4. トリガー

### 4.1. `updated_at` 自動更新トリガー

`ChatSessions` テーブルと `ExtractedInformation` テーブルのレコードが更新された際に、`updated_at` カラムを現在時刻で自動的に更新するためのトリガーと関数が定義されています。

**トリガー関数:**
```sql
CREATE OR REPLACE FUNCTION trigger_set_timestamp()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
```

**`ChatSessions` テーブルへの適用:**
```sql
CREATE TRIGGER set_timestamp_chat_sessions
BEFORE UPDATE ON ChatSessions
FOR EACH ROW
EXECUTE PROCEDURE trigger_set_timestamp();
```

**`ExtractedInformation` テーブルへの適用:**
```sql
CREATE TRIGGER set_timestamp_extracted_information
BEFORE UPDATE ON ExtractedInformation
FOR EACH ROW
EXECUTE PROCEDURE trigger_set_timestamp();
```

## 5. 設計上の考慮事項と今後の可能性

*   **`ExtractedInformation` の履歴管理:** 現在の設計では、`ExtractedInformation` テーブルに同一 `session_id` で複数のレコードが作成されることで履歴を表現できます。アプリケーション側で最新版の取得ロジックを実装する必要があります。より厳密なバージョン管理や「最新版フラグ」のようなカラムの追加も将来的には検討可能です。
*   **インデックス:** 現状、主キーと外部キー以外には明示的なインデックスは定義されていません。アプリケーションのクエリパターンが明確になった段階で、パフォーマンス向上のために適切なカラム（例: `ChatLogs.timestamp`, `ExtractedInformation.updated_at`など）へのインデックス追加を検討します。
*   **分析用途:** `raw_gemini_request`, `raw_gemini_response`, `raw_extracted_info` などのJSONBカラムは、将来的なAIの挙動分析やデバッグ、精度改善のためのデータソースとして活用できます。

以上が「AI設備仕様コンシェルジュ」のデータベース設計です。
```
