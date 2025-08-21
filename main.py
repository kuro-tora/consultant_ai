import os
import json
from typing import Dict, List, Optional
import chainlit as cl
import requests
from pydantic import BaseModel, Field
from openai import OpenAI
import firebase_admin
from firebase_admin import credentials, firestore, auth
import asyncio

# OpenAI クライアント初期化
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

class Agent:
    def __init__(self, name: str, instructions: str, output_type, model: str = "gpt-4o"):
        self.name = name
        self.instructions = instructions
        self.output_type = output_type
        self.model = model
    
    async def run(self, prompt: str):
        try:
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.instructions},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=1500
            )
            
            content = response.choices[0].message.content
            
            # 出力タイプに応じて結果を解析
            if self.output_type == InterviewQuestion:
                return MockResult(InterviewQuestion(question=content))
            elif self.output_type == ManagerAction:
                # 簡単な判定ロジック
                if "business" in content.lower() or "業務" in content:
                    return MockResult(ManagerAction(nextAgent="business_Qgenerator", reasoning=content))
                elif "emotional" in content.lower() or "感情" in content:
                    return MockResult(ManagerAction(nextAgent="emotional_Qgenerator", reasoning=content))
                else:
                    return MockResult(ManagerAction(nextAgent="nurturing", reasoning=content))
            elif self.output_type == NurturingResponse:
                is_ready = "準備ができ" in content or "開始" in content or "進め" in content
                return MockResult(NurturingResponse(message=content, is_ready_to_proceed=is_ready))
            else:
                return MockResult(self.output_type(content=content))
                
        except Exception as e:
            # エラー時のフォールバック
            if self.output_type == InterviewQuestion:
                return MockResult(InterviewQuestion(question=f"申し訳ございませんが、システムエラーが発生しました。改めて質問させていただけますでしょうか？"))
            else:
                raise e

class MockResult:
    def __init__(self, data):
        self.data = data

# Firebase初期化
cred = credentials.Certificate('serviceAccountKey.json')
firebase_admin.initialize_app(cred)

# Firebaseクライアント作成
db = firestore.client()

class InterviewQuestion(BaseModel):
    question: str = Field(description="インタビュー質問")

class ManagerAction(BaseModel):
    nextAgent: str = Field(description="次に実行するエージェント名")
    reasoning: str = Field(description="エージェント選択の理由")

class ResponseAnalysis(BaseModel):
    isComplete: bool = Field(description="回答が十分か判定")
    nextQuestionNeeded: bool = Field(description="追加質問が必要か")
    followUpQuestion: Optional[str] = Field(description="追加質問（必要な場合）")

class NurturingResponse(BaseModel):
    message: str = Field(description="ネイチャリングメッセージ")
    is_ready_to_proceed: bool = Field(description="次のフェーズに進む準備ができているか")

# プロンプト定義（修正版）
PROMPTS_manager = {
    "manager": {
        "instructions": (
            "あなたはインタビューの流れを管理するマネージャーAIです。"
            "ユーザーの回答内容を分析し、適切な次のエージェントを選択してください。"
            "\n\n利用可能エージェント："
            "\n- nurturing: インタビュー導入とユーザーの心理的安全確保"
            "\n- business_Qgenerator: 業務・経験・スキルに関する質問生成"
            "\n- emotional_Qgenerator: 感情・動機・価値観に関する質問生成"
            "\n\n段階的進行："
            "\n1. nurturing → 安心感確保後に業務質問へ"
            "\n2. business_Qgenerator → 客観的事実収集"
            "\n3. emotional_Qgenerator → 主観的要素の深掘り"
            "\n\nnextAgentで次のエージェント名を、reasoningで選択理由を日本語で出力してください。"
        )
    }
}

PROMPTS_emotional_Qgenerator = {
    "emotional_Qgenerator": {
        "instructions": ("""# 役割
あなたは主観的・感情的プロフィール収集のサポート担当です。business_Qgeneratorが収集する必須20属性の補完と、感情・価値観の深掘りを行います。

────────────────────────────────
▼20属性サポート（business_Qgeneratorで未取得時のみ）
1 情報入手日 / 2 人材ID / 3 会社略称 / 4 名前(イニシャル) / 5 人材種別1 / 6 AC在籍有無 / 7 AC在籍期間 / 8 性別 / 9 年齢 / 10 稼働率 / 11 稼働開始可能日 / 12 希望単価 / 13 並行営業 / 14 リモート希望 / 15 可能地域 / 16 英語スキル / 17 アピールポイント / 18 直近の実績 / 19 レジュメ所在LINK URL / 20 備考

▼感情・価値観深掘り（20属性収集後）
・仕事に対するモチベーション・やりがい
・キャリア志向・将来の目標  
・価値観・重視する要素
・ストレス要因・課題
・成長意欲・学習姿勢
・チームワーク・コミュニケーション

▼アルゴリズム
A 履歴確認: 20属性の取得状況を確認し、未取得があれば属性収集を優先。
B 属性収集フェーズ: 未取得属性1件につき1質問。複合質問禁止。
C 感情深掘りフェーズ: 20属性完了後に主観的要素を探る。
D 質問スタイル: オープンクエスチョン、具体的エピソード重視、1質問1論点。

常に次の未取得属性1件または感情深掘り1点に集中した日本語質問文1つのみ出力してください。
""")
    }
}

PROMPTS_business_Qgenerator = {
    "business_Qgenerator": {
        "instructions": ("""# 役割
あなたは客観プロフィール収集の主担当です。必須20属性が全て『取得 / 拒否 / 不明確定』になるまで経験・スキルの自由深掘り質問は禁止。出力は常に未取得属性1件に集中した日本語の質問文1つのみ。

────────────────────────────────
▼必須20属性（順序固定 / 途中でユーザーが先の属性を答えたら取得扱いしてスキップ）
1 情報入手日 / 2 人材ID / 3 会社略称 / 4 名前(イニシャル) / 5 人材種別1 / 6 AC在籍有無 / 7 AC在籍期間 / 8 性別 / 9 年齢 / 10 稼働率 / 11 稼働開始可能日 / 12 希望単価 / 13 並行営業 / 14 リモート希望 / 15 可能地域 / 16 英語スキル / 17 アピールポイント / 18 直近の実績 / 19 レジュメ所在LINK URL / 20 備考

▼アルゴリズム
A 各ターン直前に全履歴を走査し取得済みを判定、未取得番号リストを再構成。
B 未取得が空になるまで 1質問=リスト先頭1属性。複合質問禁止。
C 回答内に複数属性含まれたらその全て取得済みとし重複質問禁止。
D 拒否/不明=確定扱いで再質問禁止（年齢・性別など）。
E あいまい表現は同属性内で具体化再質問し確定後に次へ。
F 希望単価は『○○万円/月（税抜 or 税込） 交渉余地: ○○』表記誘導。
G 直近実績は最大3件: 役割/期間/技術/規模/成果 箇条書き。
H URL 未入手→後ほど共有依頼 + 『未入手（後ほど）』確定。
I 20属性確定後に初めて自由なスキル深掘り（全体像→代表プロジェクト→成果/強み）へ移行。
J 深掘り移行後も 1質問1論点。再び属性を直接訊かない。

▼テンプレ質問（未取得時のみ使用 / 必要最小限の敬語調整可）
1 情報入手日を YYYY-MM-DD 形式で教えてください。
2 人材ID（管理番号）があれば教えてください。
3 提案元の会社略称を教えてください。
4 レジュメ用イニシャル（例: TY）を教えてください。
5 最も強みとなる人材種別（領域）を一つ挙げてください。
6 アクセンチュア在籍経験はありますか？（有 / 無）
7 在籍期間を分かる範囲で教えてください。（無い/不明ならその旨）
8 性別を共有可能でしょうか？（任意 / 拒否可）
9 年齢または年代を共有可能でしょうか？（任意 / 拒否可）
10 希望される稼働率（例: 80%）を教えてください。
11 稼働開始可能日（最短/目安）を教えてください。
12 希望単価を『○○万円/月（税抜 or 税込） 交渉余地: ○○』形式で教えてください。
13 現在並行して他案件営業はありますか？（有 / 無）
14 リモート/出社の希望（フル / 一部（頻度）/ 問わない）を教えてください。
15 稼働可能な地域（都道府県や最寄駅レベル）を教えてください。
16 英語スキルレベル（ビジネス / 日常 / 読み書き / 不可）と根拠を教えてください。
17 アピールポイントを短いキャッチ＋簡潔補足で教えてください。
18 直近2～3件の案件実績を役割/期間/技術/規模/成果で簡潔に箇条書きください。
19 レジュメ共有リンク（Dropbox 等）があれば教えてください。無ければ後ほどでも構いません。
20 その他備考（制約・留意点など）があれば教えてください。

未取得属性が残る限り上記テンプレ以外の深掘り・複合質問・雑談は禁止。常に次の未取得1件にのみ集中した質問を1つ返してください。
""")
    }
}

PROMNPTS_NURTURING = {
    "nurturing": {
        "instructions": ("""
        あなたはインタビューの導入を担当するネイチャリングAIです。
        インタビュイーが心理的に安全な状態でインタビューに臨めるよう、以下の内容を丁寧に日本語で説明してください：
        
        1. インタビューの目的と背景
        2. 情報の取り扱いとプライバシー保護の方針
        3. インタビューの流れと所要時間
        4. インタビュイーの意見がどのように活用されるか
        5. インタビューは完全に任意であり、答えたくない質問はスキップできること
        
        インタビュイーの反応を分析し、不安や懸念がある場合は追加の説明を行ってください。
        インタビュイーが明確に了承した場合のみ、インタビュー開始の準備ができたと判断してください。
        
        is_ready_to_proceedフィールドでは、インタビュイーが次のフェーズに進む準備ができているかを示してください。
        準備ができていなければfalseを返し、さらに説明を続けてください。
        準備ができていればtrueを返し、インタビュー質問フェーズに進めることを示してください。
        """)
    }
}

# エージェント作成関数
def create_manager(custom_prompts=None):
    prompts = PROMPTS_manager.copy()
    if custom_prompts:
        for key, value in custom_prompts.items():
            if key in prompts:
                prompts[key].update(value)
    manager = Agent(
        name="インタビュー管理AI",
        instructions=prompts["manager"]["instructions"],
        output_type=ManagerAction,  
        model="gpt-4o",
    )
    return manager

def create_business_Qgenerator(custom_prompts=None):
    prompts = PROMPTS_business_Qgenerator.copy()
    if custom_prompts:
        for key, value in custom_prompts.items():
            if key in prompts:
                prompts[key].update(value)
    business_Qgenerator = Agent(
        name="業務質問生成AI",
        instructions=prompts["business_Qgenerator"]["instructions"],
        output_type=InterviewQuestion,  
    )
    return business_Qgenerator

def create_emotional_Qgenerator(custom_prompts=None):
    prompts = PROMPTS_emotional_Qgenerator.copy()
    if custom_prompts:
        for key, value in custom_prompts.items():
            if key in prompts:
                prompts[key].update(value)
    emotional_Qgenerator = Agent(
        name="感情質問生成AI",
        instructions=prompts["emotional_Qgenerator"]["instructions"],
        output_type=InterviewQuestion,  
    )
    return emotional_Qgenerator

def create_nurturing(custom_prompts=None):
    prompts = PROMNPTS_NURTURING.copy()
    if custom_prompts:
        for key, value in custom_prompts.items():
            if key in prompts:
                prompts[key].update(value)
    nurturing = Agent(
        name="ネイチャリングAI",
        instructions=prompts["nurturing"]["instructions"],
        output_type=NurturingResponse,  
    )
    return nurturing

def get_company_nurturing(company_email: str) -> str:
    doc_ref = db.collection(company_email).document("nurturing")
    doc = doc_ref.get()
    if doc.exists:
        data = doc.to_dict()
        return data.get("nurturing", "ネイチャリングの情報がありません")
    return "該当する会社が見つかりませんでした"

def firebase_login(email: str, password: str):
    api_key = os.getenv("FIREBASE_API_KEY")
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={api_key}"
    payload = {
        "email": email,
        "password": password,
        "returnSecureToken": True
    }
    response = requests.post(url, json=payload)
    data = response.json()
    if "idToken" in data:
        return data  
    else:
        raise Exception(f"ログイン失敗: {data.get('error', {}).get('message')}")

def get_account_info(id_token: str):
    api_key = os.getenv("FIREBASE_API_KEY")
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:lookup?key={api_key}"
    payload = {
        "idToken": id_token
    }
    response = requests.post(url, json=payload)
    data = response.json()
    if "users" in data:
        return data["users"][0]
    else:
        raise Exception(f"アカウント情報取得失敗: {data.get('error', {}).get('message')}")

def save_session_to_firestore(session_id: str, conversation_data: List[Dict], user_email: str):
    doc_ref = db.collection(user_email).document(session_id)
    doc_ref.set({
        "conversation": conversation_data,
        "timestamp": firestore.SERVER_TIMESTAMP,
        "session_id": session_id
    })

def get_conversation_history(user_email: str, session_id: str) -> List[Dict]:
    doc_ref = db.collection(user_email).document(session_id)
    doc = doc_ref.get()
    if doc.exists:
        data = doc.to_dict()
        return data.get("conversation", [])
    return []

# Chainlitイベントハンドラ
@cl.on_chat_start
async def on_chat_start():
    await cl.Message(content="**AI人材インタビューシステムへようこそ！**\n\nまずはログインが必要です。メールアドレスとパスワードを入力してください。").send()
    cl.user_session.set("authenticated", False)
    cl.user_session.set("current_agent", "login")
    cl.user_session.set("conversation_history", [])

@cl.on_message
async def on_message(message: cl.Message):
    current_agent = cl.user_session.get("current_agent", "login")
    authenticated = cl.user_session.get("authenticated", False)
    conversation_history = cl.user_session.get("conversation_history", [])
    
    if not authenticated and current_agent == "login":
        await handle_login(message.content)
        return
    
    # 会話履歴に追加
    conversation_history.append({
        "role": "user",
        "content": message.content,
        "timestamp": firestore.SERVER_TIMESTAMP
    })
    
    try:
        if current_agent == "nurturing":
            response = await handle_nurturing(message.content, conversation_history)
        elif current_agent == "business_Qgenerator":
            response = await handle_business_questions(message.content, conversation_history)
        elif current_agent == "emotional_Qgenerator":
            response = await handle_emotional_questions(message.content, conversation_history)
        else:
            # マネージャーによる判定
            response = await handle_manager_decision(message.content, conversation_history)
        
        # レスポンスを送信
        await cl.Message(content=response).send()
        
        # 会話履歴に追加して保存
        conversation_history.append({
            "role": "assistant",
            "content": response,
            "timestamp": firestore.SERVER_TIMESTAMP,
            "agent": current_agent
        })
        
        cl.user_session.set("conversation_history", conversation_history)
        
        # Firestoreに保存
        user_email = cl.user_session.get("user_email")
        session_id = cl.user_session.get("session_id", "default_session")
        if user_email:
            save_session_to_firestore(session_id, conversation_history, user_email)
            
    except Exception as e:
        await cl.Message(content=f"エラーが発生しました: {str(e)}").send()

async def handle_login(content: str):
    try:
        lines = content.strip().split('\n')
        if len(lines) >= 2:
            email = lines[0].strip()
            password = lines[1].strip()
        else:
            parts = content.strip().split()
            if len(parts) >= 2:
                email = parts[0]
                password = parts[1]
            else:
                await cl.Message(content="メールアドレスとパスワードを以下の形式で入力してください：\n\nemail@example.com\npassword").send()
                return
        
        auth_data = firebase_login(email, password)
        account_info = get_account_info(auth_data["idToken"])
        
        cl.user_session.set("authenticated", True)
        cl.user_session.set("user_email", email)
        cl.user_session.set("id_token", auth_data["idToken"])
        cl.user_session.set("session_id", f"session_{auth_data['localId']}")
        cl.user_session.set("current_agent", "nurturing")
        
        await cl.Message(content=f"**ログイン成功！**\n\nようこそ、{email} さん\n\nインタビューを開始いたします。").send()
        
        # ネイチャリングフェーズ開始
        nurturing_agent = create_nurturing()
        nurturing_prompt = get_company_nurturing(email)
        
        result = await nurturing_agent.run(
            f"ユーザー企業の情報: {nurturing_prompt}\n\nインタビュー開始の挨拶とオリエンテーションをお願いします。"
        )
        await cl.Message(content=result.data.message).send()
        
    except Exception as e:
        await cl.Message(content=f"ログインに失敗しました。メールアドレスとパスワードを確認してください。\n\nエラー: {str(e)}").send()

async def handle_nurturing(content: str, conversation_history: List[Dict]) -> str:
    nurturing_agent = create_nurturing()
    user_email = cl.user_session.get("user_email")
    nurturing_info = get_company_nurturing(user_email)
    
    conversation_context = "\n".join([f"{msg['role']}: {msg['content']}" for msg in conversation_history[-5:]])
    
    result = await nurturing_agent.run(
        f"企業情報: {nurturing_info}\n\n"
        f"これまでの会話:\n{conversation_context}\n\n"
        f"ユーザーの最新回答: {content}\n\n"
        f"適切なネイチャリングレスポンスを生成し、次のフェーズに進む準備ができているかを判定してください。"
    )
    
    if result.data.is_ready_to_proceed:
        cl.user_session.set("current_agent", "business_Qgenerator")
        return result.data.message + "\n\n**それでは人材情報の収集を開始させていただきます。**"
    
    return result.data.message

async def handle_business_questions(content: str, conversation_history: List[Dict]) -> str:
    business_agent = create_business_Qgenerator()
    
    conversation_context = "\n".join([f"{msg['role']}: {msg['content']}" for msg in conversation_history[-10:]])
    
    result = await business_agent.run(
        f"これまでの会話履歴:\n{conversation_context}\n\n"
        f"ユーザーの最新回答: {content}\n\n"
        f"必須20属性の取得状況を確認し、未取得の属性について次の質問を1つ生成してください。"
    )
    
    return result.data.question

async def handle_emotional_questions(content: str, conversation_history: List[Dict]) -> str:
    emotional_agent = create_emotional_Qgenerator()
    
    conversation_context = "\n".join([f"{msg['role']}: {msg['content']}" for msg in conversation_history[-8:]])
    
    result = await emotional_agent.run(
        f"これまでの会話履歴:\n{conversation_context}\n\n"
        f"ユーザーの最新回答: {content}\n\n"
        f"感情・動機・価値観の深掘りのための次の質問を1つ生成してください。"
    )
    
    return result.data.question

async def handle_manager_decision(content: str, conversation_history: List[Dict]) -> str:
    manager = create_manager()
    
    conversation_context = "\n".join([f"{msg['role']}: {msg['content']}" for msg in conversation_history[-5:]])
    
    result = await manager.run(
        f"これまでの会話:\n{conversation_context}\n\n"
        f"ユーザーの最新回答: {content}\n\n"
        f"適切な次のエージェントを選択してください。"
    )
    
    next_agent = result.data.nextAgent
    cl.user_session.set("current_agent", next_agent)
    
    if next_agent == "business_Qgenerator":
        return await handle_business_questions(content, conversation_history)
    elif next_agent == "emotional_Qgenerator":
        return await handle_emotional_questions(content, conversation_history)
    else:
        return f"エージェント切り替え: {next_agent}\n理由: {result.data.reasoning}"

if __name__ == "__main__":
    cl.run()
