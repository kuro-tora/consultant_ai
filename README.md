# 業務・案件マッチングシステム

## 概要

本システムは、Chainlit上で動作するAIエージェントを活用した業務・案件マッチングのためのインタビューシステムのPython実装です。個人のスキル、経験、希望条件を詳細にヒアリングし、最適な業務や案件とのマッチングを支援します。

## 主な機能

- **多段階インタビュー**: ネイチャリング、業務詳細、希望・要望の3フェーズ構成
- **AI駆動質問生成**: 文脈に応じた適切な質問を動的に生成
- **リアルタイム進行管理**: 残り時間やトピックカバー状況を考慮した最適な進行
- **Firebase連携**: 安全なデータ保存とユーザー認証

## ファイル説明

### main.py

システム全体のPythonコードが記述されているファイル。業務・案件マッチング用の各種AIエージェントの定義と実行ロジックが含まれています。

### .env

APIキーが記述されているファイルのため、以下のAPIキーを取得して記述する。
＜取得するAPI＞
OPENAI_API_KEY
FIREBASE_API_KEY
FIREBASE_AUTH_DOMAIN
FIREBASE_PROJECT_ID
FIREBASE_STORAGE_BUCKET
FIREBASE_MESSAGING_SENDER_ID
FIREBASE_APP_ID
MEASUREMENT_ID
FIREBASE_DATABASE_URL
GOOGLE_APPLICATION_CREDENTIALS：serviceAccountKey.jsonのパス

### requirements.txt

使用しているライブラリのバージョンを記述している。

### secrets.yaml

.envファイルと同様にAPIキーが記述されているため、APIキーを取得して記述する。
GOOGLE_APPLICATION_CREDENTIALSはserviceAccountKey.jsonのパスにする。

### serviceAccountKey.json

googleのserviceAccountKeyのファイルのため、googleから発行してファイルを取得し、他ファイルと同じ階層に追加する。

### chainlit.md

システムのウェルカムページの内容を定義するファイル。業務・案件マッチングシステムの説明が記載されています。

## 実行方法

### 前準備

1. データベース関連の事前準備を完了させる
2. 各APIキーを取得し、.envファイルとsecrets.yamlに記述する
3. GoogleのserviceAccountKey.jsonを取得する
4. 全てのファイルが同じ階層にあることを確認する

### 起動手順

```bash
# 仮想環境の作成と有効化
python -m venv .venv
source .venv/bin/activate  # macOS/Linux
# または
.venv\Scripts\activate  # Windows

# 依存関係のインストール
pip install -r requirements.txt

# アプリケーションの起動
chainlit run main.py
```

### 使用方法

1. ブラウザでシステムにアクセス
2. Firebase認証でログイン
3. 「開始」と入力してインタビューを開始
4. AIエージェントの質問に回答
5. 自動的に業務詳細→希望・要望フェーズに進行
6. インタビュー完了後、マッチング分析結果を受領

### 実行

「pip install -r requirements.txt」をターミナルにおいて実行する。
「chainlit run main.py」をターミナルにおいて実行する。

### チャット

ログイン画面においてAuthenticationに登録したメールアドレスとパスワードを入力する。
チャット画面において、各質問に回答する。
30分後にチャットが終了し、内容がFirebaseに記録される。
