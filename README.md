# コンサルAI

## 概要

本システムは、Chainlit上で動作するAIエージェントを活用したインタビューモデルのPython実装です。

## ファイル説明

### main.py

システム全体のpythonが書かれているファイル

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
requirements.txt
使用しているライブラリのバージョンを記述している。

### secrets.yaml

.envファイルと同様にAPIキーが記述されているため、APIキーを取得して記述する。
GOOGLE_APPLICATION_CREDENTIALSはserviceAccountKey.jsonのパスにする。

### serviceAccountKey.json

googleのserviceAccountKeyのファイルのため、googleから発行してファイルを取得し、他ファイルと同じ階層に追加する。

### read me

本ドキュメント

## 実行方法

### 前準備

データベース関連の事前準備を終了させたものとする。（技術ドキュメント（システム）の4.4）
各APIキーを取得し、.envファイルとsecrets.yamlに記述する。
googleのserviceAccountKey.jsonを取得する。
全てのファイルが同じ階層にあることを確認する。

### 実行

「pip install -r requirements.txt」をターミナルにおいて実行する。
「chainlit run main.py」をターミナルにおいて実行する。

### チャット

ログイン画面においてAuthenticationに登録したメールアドレスとパスワードを入力する。
チャット画面において、各質問に回答する。
30分後にチャットが終了し、内容がFirebaseに記録される。
