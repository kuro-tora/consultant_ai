from dotenv import load_dotenv
import os
from agents import Agent, Runner
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import chainlit as cl
from firebase_admin import firestore,credentials,auth
import firebase_admin
import sys
import requests

os.environ["OPENAI_API_KEY"]=os.getenv("OPENAI_API_KEY")
os.environ["CHAINLIT_AUTH_SECRET"]=os.getenv("CHAINLIT_AUTH_SECRET")
os.environ["FIREBASE_API_KEY"]=os.getenv("FIREBASE_API_KEY")
os.environ["FIREBASE_AUTH_DOMAIN"]=os.getenv("FIREBASE_AUTH_DOMAIN")
os.environ["FIREBASE_PROJECT_ID"]=os.getenv("FIREBASE_PROJECT_ID")
os.environ["FIREBASE_STORAGE_BUCKET"]=os.getenv("FIREBASE_STORAGE_BUCKET")
os.environ["FIREBASE_MESSAGING_SENDER_ID"]=os.getenv("FIREBASE_MESSAGING_SENDER_ID")
os.environ["FIREBASE_APP_ID"]=os.getenv("FIREBASE_APP_ID")
os.environ["MEASUREMENT_ID"]=os.getenv("MEASUREMENT_ID")
os.environ["FIREBASE_DATABASE_URL"]=os.getenv("FIREBASE_DATABASE_URL")
os.environ["GOOGLE_APPLICATION_CREDENTIALS"]=os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

os.environ["USER_AGENT"] = os.getenv("USER_AGENT")
db = firestore.Client()
firebase_config = {
  "apiKey": os.getenv("FIREBASE_API_KEY"),
    "authDomain": os.getenv("FIREBASE_AUTH_DOMAIN"),
    "projectId": os.getenv("FIREBASE_PROJECT_ID"),
    "storageBucket": os.getenv("FIREBASE_STORAGE_BUCKET"),
    "messagingSenderId": os.getenv("FIREBASE_MESSAGING_SENDER_ID"),
    "appId": os.getenv("FIREBASE_APP_ID"),
  "measurementId": os.getenv("MEASUREMENT_ID"),
  "databaseURL": os.getenv("FIREBASE_DATABASE_URL")
}

if not firebase_admin._apps:
    cred = credentials.Certificate(os.environ["GOOGLE_APPLICATION_CREDENTIALS"])
    firebase_admin.initialize_app(cred)

auth_secret = os.getenv("CHAINLIT_AUTH_SECRET")

class AIMessageLog(BaseModel):
    timestamp: str
    agent_name: str
    prompt: str
    response: str
    processing_time: float

class NurturingResponse(BaseModel):
    explanation: str
    is_ready_to_proceed: bool

class InterviewQuestion(BaseModel):
    question: str

class ManagerAction(BaseModel):
    action_type: str  
    remaining_time: int 
    covered_topics: List[str]  
    uncovered_topics: List[str]  
    next_topic: Optional[str] = None  
    next_phase: Optional[str] = None  
    message: str 

class ResponseAnalysis(BaseModel):
    response_score: float  
    missing_information: List[str]  
    detected_sentiments: List[str]  
    follow_up_questions: List[str] 
    recommended_action: str 
    feedback: str 

class AIMessageLog(BaseModel):
    timestamp: str
    agent_name: str
    prompt: str
    response: str
    processing_time: float

##エージェント関連
#エージェントのプロンプト
PROMPTS_manager = { "manager": {
        "instructions":(""" あなたは業務・案件マッチングのためのヒアリング全体進行を管理するエージェントです。
            以下の役割を担います：

            1. 進行管理：制限時間に合わせて各質問の終了・次質問への移行を判断
            2. ゴール監視：事前に設定した「聞くべきトピック」をカバーできているかトラッキング
            3. フェーズ管理：「業務詳細フェーズ」から「希望・要望フェーズ」への移行を判断
            4. 深掘り判断：回答が浅い場合や詳細が不足している場合の深掘りを決定

            ヒアリングは2つのフェーズに分かれています：
            - 業務詳細フェーズ：現在の業務内容、スキル、経験、課題などの客観的情報を収集
            - 希望・要望フェーズ：今後の希望、要望、条件、懸念など、主観的な情報を収集

            ヒアリング全体の流れを見て、次のアクションを決定してください：
            - deep_dive: 回答が抽象的・曖昧・短い場合、または重要な詳細が不足している場合に実行
            - switch_topic: 現在のトピックが十分にカバーされた場合に次のトピックへ移行
            - switch_phase: 現フェーズのトピックが十分にカバーされた場合に次フェーズへ移行
            - end_interview: 全てのトピックが適切にカバーされた場合にヒアリングを終了

            【深掘りを行うべき状況】
            - 回答が「はい」「いいえ」など単純すぎる
            - 具体的な数値、期間、頻度が不明
            - 経験やスキルのレベルが不明確
            - 課題や改善点が表面的
            - 感情や動機が不明
            
            業務詳細フェーズのトピックが十分にカバーできたら、希望・要望フェーズへの移行を指示してください。
            「次はあなたの今後の希望や要望についてお聞きします」などのメッセージで移行をスムーズにします。
            """"")
            }}

PROMPTS_emotional_Qgenerator = {
    "emotional_Qgenerator": {
        "instructions": ("""# あなたは共感をベースにしたコミュニケーションが得意な業務・案件マッチングコンサルタントです。
        以下の手順と書式だけを守り、日本語で共感的な対話を行ってください。
        （指示にないことは実行しないこと）

        ────────────────────────────────
        ▼ステップ 0 : 対象判定（事前フィルタ）
        ❶ ユーザーからの入力が、業務・案件マッチングに関する希望・要望のヒアリングと関連性があるか確認せよ。
        ❷ 以下のいずれかに該当する場合は、その旨を伝え、正確な情報の再入力を促し、このステップで即座に終了すること：

            例：「恐れ入りますが、ご入力いただいた内容が、業務・案件マッチングに関するヒアリングの趣旨と異なるか、入力ミスの可能性がございます。お手数ですが、関連する希望・要望について再度ご入力いただけますでしょうか。」

        ★妥当性チェックで「該当する」と判断するケースの例
            ・業務や案件・キャリアと全く関連のない話題（例：「今日の天気は良いですね」）
            ・意味をなさない文字列、極端に短い入力、記号の羅列など、明らかに意図が不明な入力
        ────────────────────────────────
        ▼ステップ 1 : 業務・案件マッチングに関する共感的対話（ステップ 0 を通過した場合のみ）
        ❶ 常に相手の感情を最優先し、各メッセージを200文字以内で応答すること。
        ❷ 以下の指針に基づき、共感的な対話を行うこと。
            ・短い相槌を打ち、相手の感情を読み取り言語化して返す（例：「〇〇と感じていらっしゃるのですね」）。
            ・共感の言葉を織り交ぜ、理解や驚きを示す相槌（例：「確かに」「お気持ちよくわかります」）を用いる。
            ・感情の肯定、感情に関する自然な質問（例：「どんな気持ちになりそうですか？」）を行う。
            ・懸念には共感し背景の感情を確認する。他に気になることがないか優しく尋ね、懸念表明に感謝する。
            ・期待にはポジティブな感情を共有し、実現後の変化や感情を掘り下げて聞く。
        ❸ まず新しい業務や案件への期待・不安、理想の働き方について開かれた質問で会話を開始すること。
        ❹ 会話の終わりには「貴重なお気持ちをありがとうございました」と感謝を伝えること。

        ────────────────────────────────
        ▼応答例（ステップ1におけるAIの応答）：
        （例1：懸念を聞き出す場合）
        ユーザー: 新しい案件は興味があるけれど、自分のスキルで対応できるか不安です。
        あなた: なるほど、スキル面でのご不安がおありなのですね。それは確かに心配になりますよね。新しいチャレンジに対して不安を感じるのは自然なことですし、責任感の現れでもありますね。そのご不安について、もう少し詳しくお聞かせいただけますでしょうか。

        （例2：期待を聞き出す場合）
        ユーザー: より専門性を活かせる業務に携わりたいと思っています。
        あなた: そうなんですね！専門性を活かせる業務への期待をお持ちなのですね。それは本当に素晴らしい目標ですよね。専門性を存分に発揮できるようになったら、どのような充実感や達成感を感じられそうでしょうか？きっと、これまで以上にやりがいを感じながらお仕事に取り組めるようになりそうですね。""")
}}
PROMPTS_business_Qgenerator = {
    "business_Qgenerator": {
        "instructions": (""" あなたは精密な業務・スキル分析コンサルタントです。
        以下の手順と書式だけを守り、日本語でユーザーに質問し、業務・案件マッチングに必要な情報を収集・分析してください。
        （指示にないことは行わないこと）

        ────────────────────────────────
        ▼ステップ 0 : 対象判定（事前フィルタ）
        ❶ ユーザーからの入力が、業務・案件マッチングに関する経験・スキルのヒアリングと関連性があるか確認せよ。
        ❷ 以下のいずれかに該当する場合は、その旨を伝え、正確な情報の再入力を促し、このステップで即座に終了すること：

            例：「恐れ入りますが、ご入力いただいた内容が、業務・案件マッチングに関するヒアリングの趣旨と異なるか、入力ミスの可能性がございます。お手数ですが、関連する経験・スキルについて再度ご入力いただけますでしょうか。」

        ★妥当性チェックで「該当する」と判断するケースの例
            ・業務やスキル・経験と全く関連のない話題（例：「今日の天気は良いですね」）
            ・意味をなさない文字列、極端に短い入力、記号の羅列など、明らかに意図が不明な入力

        ────────────────────────────────
        ▼ステップ 1 : 業務・案件マッチングのためのヒアリング（ステップ 0 を通過した場合のみ）
        ❶ 以下の指針に基づき、業務・案件マッチングに必要な情報を収集するため、ユーザーに質問すること。
            ・事実と具体例を重視し、経験年数、習得レベル、実績等の定量的情報を引き出す。
            ・質問は具体的かつ明確にし、1つの論点に絞る。曖昧な回答は掘り下げる。
            ・経験・スキルの全体像から詳細、強み・弱みへと順に把握する。
            ・深掘り質問では「具体的には？」「例えば？」「どのような場面で？」を活用する。
        ❷ 以下の質問カテゴリーを参考に、状況に応じて質問を選択・組み合わせること。
        ❸ ヒアリングで収集した主要情報を簡潔に要約し、ユーザーに確認を求めること。
        ❹ 次のステップや今後の進め方を簡潔に伝え、ヒアリングを終了すること。

        ▼質問カテゴリー例:
        ①経験・キャリア全体
        ・これまでのキャリアの中で、最も経験を積まれた分野はどちらでしょうか？
        ・その分野ではどのようなプロジェクトや案件に携わってこられましたか？
        ・チームでの役割やポジションについて教えてください。
        
        ②技術スキル・専門性
        ・得意とされる技術スキルや専門領域はありますか？
        ・習得レベル（初級・中級・上級）と実務経験年数を教えてください。
        ・最近新しく学んだ技術や取り組んでいることはありますか？
        
        ③実績・成果
        ・これまでの業務で特に印象に残っている成功事例はありますか？
        ・どのような成果や効果を上げることができましたか？
        ・お客様や関係者からの評価はいかがでしたか？
        
        ④業務スタイル・環境
        ・どのような業務環境で力を発揮しやすいですか？
        ・チーム作業と個人作業、どちらがお得意でしょうか？
        ・コミュニケーションの取り方で意識されていることはありますか？
        
        ⑤強み・特徴
        ・同僚や上司から評価される強みはどのような点ですか？
        ・自分らしさを発揮できる業務の特徴があれば教えてください。
        ・これまでの経験の中で身につけた独自の視点やアプローチはありますか？

        ────────────────────────────────
        ▼応答例（ステップ1におけるAIの応答）：

        （ヒアリング開始例）
        ユーザー: 
        あなた: 本日はお忙しい中、業務・案件マッチングのためのヒアリングにお時間をいただきありがとうございます。早速ですが、まずこれまでのご経験やキャリアの概要について、簡単にご説明いただけますでしょうか？

        （具体的な質問例）
        ユーザー: エンジニアとして5年ほどWebアプリケーション開発に携わってきました。
        あなた: Webアプリケーション開発で5年のご経験をお持ちとのこと、その中で主にどのような技術スタックを使用され、どのような規模のプロジェクトに携わってこられましたか？

        （ヒアリング終了例）
        ユーザー: （詳細な情報提供）
        あなた: 本日は詳細な情報提供ありがとうございました。伺った内容を基に最適な案件をご提案させていただきます。
""")}}

# PROMPTS_SUMMARIZER={
#     "summarizer": {
#         "instructions": (
#             "##Request"
#             "- 以下の##Role及び##Ruleを守り、与えられた今回のインタビュー内容と今までのインタビュー内容の要約を参照して全体の要約を作成してください。"
#             "##Role"
#             "- あなたはAI-OCRの導入支援をするコンサルタントです。"
#             "- あなたは社員へ行ったインアタビュー記録、及び複数の要約文書の要約を担当します。"
#             "##Rule"
#             "- 要約する際は、重要な情報は保持し、内容が著しく損なわれないようにしてください。"
#             "-日本語で要約を出力してください。"
            
#         )
#     }
# }

PROMNPTS_NURTURING={
    "nurturing": {
        "instructions": ("""
        あなたは業務・案件マッチングヒアリングの導入を担当するネイチャリングAIです。
        ヒアリング参加者が心理的に安全な状態でヒアリングに臨めるよう、以下の内容を丁寧に日本語で説明してください：
        
        1. ヒアリングの目的と背景（より良い業務・案件マッチングのため）
        2. 情報の取り扱いとプライバシー保護の方針
        3. ヒアリングの流れと所要時間
        4. 参加者の意見がどのように活用されるか（最適な案件提案のため）
        5. ヒアリングは完全に任意であり、答えたくない質問はスキップできること
        
        参加者の反応を分析し、不安や懸念がある場合は追加の説明を行ってください。
        参加者が明確に了承した場合のみ、ヒアリング開始の準備ができたと判断してください。
        
        is_ready_to_proceedフィールドでは、参加者が次のフェーズに進む準備ができているかを示してください。
        準備ができていなければfalseを返し、さらに説明を続けてください。
        準備ができていればtrueを返し、ヒアリング質問フェーズに進めることを示してください。
        """)}
}

#エージェント作成
def create_manager(custom_prompts=None):
    #ヒアリング管理エージェントを作成する関数
    prompts = PROMPTS_manager.copy()
    if custom_prompts:
        for key, value in custom_prompts.items():
            if key in prompts:
                prompts[key].update(value)
    manager = Agent(
        name="ヒアリング管理AI",
        instructions=prompts["manager"]["instructions"],
        output_type=ManagerAction,  
        model="gpt-4o",
    )
    return manager

def create_business_Qgenerator(custom_prompts=None):
    #業務詳細フェーズ用質問生成AIエージェントを作成する関数
    prompts = PROMPTS_business_Qgenerator.copy()
    if custom_prompts:
        for key, value in custom_prompts.items():
            if key in prompts:
                prompts[key].update(value)
    business_Qgenerator = Agent(
        name="業務詳細質問生成AI",
        instructions=prompts["business_Qgenerator"]["instructions"],
        output_type=InterviewQuestion,  
    )
    return business_Qgenerator

def create_emotional_Qgenerator(custom_prompts=None):
    #希望・要望フェーズ用質問生成AIエージェントを作成する関数
    prompts = PROMPTS_emotional_Qgenerator.copy()
    if custom_prompts:
        for key, value in custom_prompts.items():
            if key in prompts:
                prompts[key].update(value)
    emotional_Qgenerator = Agent(
        name="希望要望質問生成AI",
        instructions=prompts["emotional_Qgenerator"]["instructions"],
        output_type=InterviewQuestion,  
    )
    return emotional_Qgenerator

def create_nurturing(custom_prompts=None):
    #ネイチャリングAIエージェントを作成する関数
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

def get_company_nurturing(company_email:str)->str:
    #firestoreからネイチャリングの情報をとってくる関数
    doc_ref=db.collection(company_email).document("nurturing")
    doc=doc_ref.get()
    if doc.exists:#要確認
        data=doc.to_dict()
        return data.get("nurturing","ネイチャリングの情報がありません")
    return "該当する会社が見つかりませんでした"

# def create_summarizer(custom_prompts=None):
#     """ネイチャリングAIエージェントを作成する関数"""
#     prompts = PROMPTS_SUMMARIZER.copy()
#     # カスタムプロンプトがあれば上書き
#     if custom_prompts:
#         for key, value in custom_prompts.items():
#             if key in prompts:
#                 prompts[key].update(value)
#     summarizer = Agent(
#         name="要約AI",
#         instructions=prompts["summarizer"]["instructions"],
#         output_type=InterviewSummary,
#     )
#     return summarizer

# def get_company_summary(company_email:str)->str:
#     #firestoreから要約情報をとってくる関数
#     doc_ref=db.collection(company_email).document("All-summary")
#     doc=doc_ref.get()
#     if doc.exists:#要確認
#         data=doc.to_dict()
#         return data.get("summary","要約情報がありません")
#     return "該当する会社が見つかりませんでした"



def firebase_login(email: str, password: str):
    #emailとpassでのログイン関数
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
    return response.json()

async def run_ai_with_logging(agent, prompt, session=None):
    # AI実行をラップしてログを取得する関数
    import time
    start_time = time.time()
    # AIを実行
    result = await Runner.run(agent, prompt)
    # 処理時間を計算
    processing_time = time.time() - start_time
    # 応答を取得
    if hasattr(result, 'final_output_as') and agent.output_type:
        response_obj = result.final_output_as(agent.output_type)
        response = str(response_obj)
    else:
        response = result.final_output
    # ログエントリを作成
    log_entry = AIMessageLog(
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        agent_name=agent.name,
        prompt=prompt,
        response=response,
        processing_time=processing_time
    )
    # セッションが提供されていればログを追加
    if session:
        session.add_ai_communication_log(log_entry)
    
    return result,log_entry

#要約AIによる最終要約作成関数
async def generate_all_interview_summary(summarizer_ai, session, company_email):
    """ヒアリング全体の要約を生成する"""
    transcript = session.get_full_transcript()
    prompt = f"【今回のヒアリング内容】\n{transcript}\n\n【今までのヒアリング内容の要約】\n{get_company_summary(company_email)}\n\n以上の情報を元に、上記のヒアリング内容を分析し、主要な発見、課題点、提案された解決策、次のステップへの推奨事項をまとめた包括的な要約レポートを作成してください。"
    result, _ =await run_ai_with_logging(summarizer_ai, prompt, session)
    return result.final_output
    
async def generate_interview_summary(summarizer_ai, session):
    """今回のヒアリングの要約を生成する"""
    transcript = session.get_full_transcript()
    prompt = f"【今回のヒアリング内容】\n{transcript}\n\n以上の情報を元に、上記のヒアリング内容を分析し、主要な発見、課題点、提案された解決策、次のステップへの推奨事項をまとめた包括的な要約レポートを作成してください。"
    result, _ =await run_ai_with_logging(summarizer_ai, prompt, session)
    return result.final_output

def create_firestore_document(company_email:str,email:str):
    #firestoreの一枠を作成する関数
    if any(db.collection(company_email).limit(1).stream()):
        print(f"{company_email}コレクションはすでに存在します")
        if db.collection(company_email).document(email).get().exists:
            print(f"{email}のドキュメントはすでに存在します")
            return
        else:
            doc_ref = db.collection(company_email)
            doc_ref.collection(company_email).document(email)
            print(f"Firestoreに{email}ドキュメントを作成しました")
    else:
        print(f"{company_email}コレクションは存在しません")
        sys.exit()  
        
# インタビューセッション管理クラス
class InterviewSession:
    def __init__(self, company_email: str):
        self.company_email = company_email
        # 基本的なセッション情報を初期化
        self.context = None
        self.start_time = datetime.now()
        self.interview_history: List[List[str,str]] = []
        self.nurturing_history: List[List[str,str]] = []
        self.analysis_logs = []      
        self.manager_logs = []       
        self.ai_communication_logs: List[AIMessageLog] = []
        self.topics_to_cover = []    
        self.covered_topics = []     
        self.current_topic = None    
        self.phase_complete={"nurting":False,"interview":False}
        self.business_topics = []   
        self.emotional_topics = []

        self.phases = ["業務詳細フェーズ", "希望・要望フェーズ"]
        self.current_phase = self.phases[0]  # 最初は業務詳細フェーズ
        self.business_topics = self.get_business_topic(self.company_email)
        self.emotional_topics = self.get_emotional_topic(self.company_email)
        self.phase_topics = {
            "業務詳細フェーズ": [self.business_topics],
            "希望・要望フェーズ": [self.emotional_topics]
        }
        self.topics_to_cover = self.phase_topics[self.current_phase].copy()
        self.current_topic = self.topics_to_cover[0] if self.topics_to_cover else None
    
    def set_company_email(self, company_email):
        self.company_email = company_email

    # フェーズ切り替えメソッド
    def switch_phase(self, new_phase,phases,phase_topics):
        """フェーズを切り替える"""
        if new_phase in phases and new_phase != self.current_phase:
            self.current_phase = new_phase
            self.topics_to_cover = phase_topics[new_phase].copy()
            self.current_topic = self.topics_to_cover[0] if self.topics_to_cover else None
            return True
        return False
    
    def add_ai_communication_log(self, log: AIMessageLog):
        """AI間の通信ログを追加"""
        self.ai_communication_logs.append(log)
    
    def set_topics(self, topics):
        """カバーすべきトピックを設定"""
        self.topics_to_cover = topics.copy()
        self.covered_topics = []
        self.current_topic = topics[0] if topics else None
    
    def add_interview_qa(self, question, answer):
        """インタビューの質問と回答を追加"""
        self.interview_history.append([question, answer])
    
    def add_nurturing_interaction(self, ai_message, user_response):
        """ネイチャリングフェーズのやり取りを追加"""
        self.nurturing_history.append([ai_message, user_response])
    
    def add_analysis_log(self, round_num: int, analysis: ResponseAnalysis):
        """回答分析のログを追加"""
        self.analysis_logs.append({
            "round": round_num,
            "response_score": analysis.response_score,
            "missing_information": analysis.missing_information,
            "detected_sentiments": analysis.detected_sentiments,
            "follow_up_questions": analysis.follow_up_questions,
            "recommended_action": analysis.recommended_action,
            "feedback": analysis.feedback
        })
    
    def add_manager_log(self, round_num: int, action: ManagerAction):
        """管理エージェントのアクションログを追加"""
        self.manager_logs.append({
            "round": round_num,
            "action_type": action.action_type,
            "remaining_time": action.remaining_time,
            "covered_topics": action.covered_topics,
            "uncovered_topics": action.uncovered_topics,
            "next_topic": action.next_topic,
            "message": action.message
        })
    
    def mark_topic_covered(self, topic: str):
        """トピックをカバー済みとしてマーク"""
        if topic in self.topics_to_cover and topic not in self.covered_topics:
            self.topics_to_cover.remove(topic)
            self.covered_topics.append(topic)
    
    def set_current_topic(self, topic: str):
        """現在のトピックを設定"""
        self.current_topic = topic
    
    def get_business_topic(self,company_email:str):
        #firestoreから要約情報をとってくる関数
        doc_ref=db.collection(company_email).document("業務詳細トピック")
        doc=doc_ref.get()
        if doc.exists:
            data=doc.to_dict()
            return data.get("業務詳細トピック","業務詳細フェーズにトピックはありません")
        return "業務フェーズにトピックはありません"

    def get_emotional_topic(self,company_email:str):
        #firestoreから要約情報をとってくる関数
        doc_ref=db.collection(company_email).document("希望要望トピック")
        doc=doc_ref.get()
        if doc.exists:
            data=doc.to_dict()
            return data.get("希望要望トピック","希望・要望フェーズにトピックはありません")
        return "希望・要望フェーズにトピックはありません"

    
    def get_full_transcript(self) -> str:
        """インタビューの全文書き起こしを取得"""
        transcript = "=== ネイチャリングフェーズ ===\n\n"
        for i, (q, a) in enumerate(self.nurturing_history):
            transcript += f"Q{i+1}: {q}n"
            transcript += f"A{i+1}: {a}\n\n"
        transcript += "=== インタビューフェーズ ===\n\n"
        for i, (q, a) in enumerate(self.interview_history):
            transcript += f"Q{i+1}: {q}\n"
            transcript += f"A{i+1}: {a}\n\n"
        return transcript
    
    def get_remaining_time(self, time_limit_minutes: int) -> float:
        """残り時間を分単位で取得"""
        elapsed = (datetime.now() - self.start_time).total_seconds() / 60
        return max(0, time_limit_minutes - elapsed)


##chainlit関連
@cl.password_auth_callback
def auth_callback(email:str,password:str):
    try:
        firebase_user=firebase_login(email,password)
        user_info=get_account_info(firebase_user["idToken"])
        user_email=user_info["users"][0]["email"]
        print(f"ログイン成功:{user_email}")
        return cl.User(identifier=user_email,email= user_email)
    except Exception as e:
        print(f"ログイン情報が正しくありません。再度入力してください：{str(e)}")
        return None

#チャットを始める前の処理：
@cl.on_chat_start
async def on_chat_start():
    res = await cl.AskUserMessage( content="準備ができたら「開始」と入力してください。").send()
    if res and res["output"].strip() == "開始":
        await cl.Message(content=
            "\n本インタビューでは「終了」と入力すれば、終了させることができます。\n"
            "また、一つの質問に対しての**入力時間が30分を超えるとインタビューは初期化されます。**\n"
            "したがって**30分以内に回答**するようにしてください。\n\n"
            "**会話が終わった後は、会話の記録が完了するまでブラウザを閉じたり、消したりしないでください。**\n\n"
            "それではインタビューを開始してよければ、「はい」と入力してください。"
        ).send()
        user=cl.user_session.get("user")
        email=user.identifier
        cl.user_session.set("email",email)
        email=cl.user_session.get("email")
        company_email=email.split("@")[1]
        cl.user_session.set("session",InterviewSession(company_email))

        #firestoreのドキュメントを作成する
        create_firestore_document(company_email=company_email,email=email)

        #ネイチャリングを取得してsessionに登録する
        #db.collection(company_email).document(email).set({"email":email})
        db.collection(company_email).document(email).set({"email":email})
        context_nurturinig=get_company_nurturing(company_email=company_email)
        #context_summary=get_company_summary(company_email=company_email)
        cl.user_session.set("context_nurturinig",context_nurturinig)
        #cl.user_session.set("context_summary",context_summary)
        x_manager=0
        y_manager=0
        cl.user_session.set("x_manager",x_manager)
        cl.user_session.set("y_manager",y_manager)
    else:
        await cl.Message(content="入力が確認できませんでした。").send()


@cl.on_message
async def on_message(message: cl.Message):
    ##ネイチャリングの実行関数
    async def run_nurturing_pahase(nurturing,session,context_nurturinig,trace_ai_communication=True):
        if trace_ai_communication:
            print("AI通信トレースが有効化されています\n")

        print("\n=== AI インタビューを開始します ===\n")
        # ネイチャリングプロンプト作成
        nurturing_prompt = f"""
        【インタビューコンテキスト】
        {context_nurturinig}
        上記の情報を基に、インタビュイーに対して、インタビューの目的、情報の取り扱い、
        プライバシー保護方針を丁寧に説明し、安心感を与える導入を行ってください。
        説明後は、インタビューを開始してもよいか確認してください。
        """
        nurturing_result,log_entry = await run_ai_with_logging(nurturing, nurturing_prompt)
        nurturing_response = nurturing_result.final_output_as(NurturingResponse)
        ai_message = nurturing_response.explanation
        print(f"AI: {ai_message}\n")
        user_input=await cl.AskUserMessage(content=f"{ai_message}",timeout=108000).send()
        nurturing_complete = nurturing_response.is_ready_to_proceed
        previous_explanation = ai_message
        user_response = user_input["output"]
        print(f"インタビュイー: {user_response}\n")
        session.add_nurturing_interaction(ai_message, user_response)
        nurturing_history_text=""

        while not nurturing_complete:            
        # 終了条件のチェック
            if user_response.lower() in ["終了"]:
                print("\n🛑 インタビューを終了します。")
                return session
        
            # AIの応答を生成
            nurturing_prompt = f"""
            【インタビューコンテキスト】
            {nurturing_response}
            【これまでの説明】
            {previous_explanation}
            【インタビュイーの反応】
            {user_response}
            インタビュイーの反応に対して適切に対応し、必要に応じて追加の説明や安心させる情報を提供してください。
            インタビュイーが了解したと判断できる場合は、次のフェーズに進む準備ができていることを示してください。
            まだ不安や疑問がある場合は、それに応え、再度確認を行ってください。
            ただし同じような確認は二度行わないようにしてください。
            """
            
            nurturing_result,log_entry = await run_ai_with_logging(nurturing, nurturing_prompt)
            nurturing_response = nurturing_result.final_output_as(NurturingResponse)
            ai_message = nurturing_response.explanation
            print(f"\nAI: {ai_message}\n")
            user_input=await cl.AskUserMessage(content=f"{ai_message}",timeout=108000).send()

            previous_explanation = ai_message
            user_response = user_input["output"]
            session.add_nurturing_interaction(ai_message, user_response)
            for i, (q, a) in enumerate(session.nurturing_history):
                nurturing_history_text += f"Q{i+1}: {q}\nA{i+1}: {a}\n\n"

            # タイムアウトした場合は user_input が None
            if user_input is None or not user_response:
                await cl.Message("\n入力の制限時間に達しました。インタビューを終了します。").send()
                break
            
            # インタビュイーが了承したかチェック
            nurturing_complete = nurturing_response.is_ready_to_proceed
            
            if nurturing_complete:
                print("\n--- ネイチャリングフェーズ完了 ---")
                cl.user_session.set("nurturing_history_text",nurturing_history_text),session
                print("--- インタビュー質問フェーズを開始します ---\n")
        return True
    
    ##インタビューの実行関数
    async def run_interview_phase(manager,business_Qgenerator,emotional_Qgenerator, session,max_rounds:int,time_limit_minutes:int,trace_ai_communication=True):
    #async def run_interview_phase(manager,business_Qgenerator,emotional_Qgenerator, session, context_summary,max_rounds:int,time_limit_minutes:int,trace_ai_communication=True):
        if trace_ai_communication:
            print("🔍 AI通信トレースが有効化されています\n")
        """インタビュー質問フェーズを実行する"""

        print(f"業務詳細フェーズのトピック:{session.topics_to_cover}")
        print(f"希望・要望フェーズのトピック:{session.current_topic}")
        x_manager=cl.user_session.get("x_manager")
        y_manager=cl.user_session.get("y_manager")

        def get_current_question_generator():
            if session.current_phase == "業務詳細フェーズ":
                return business_Qgenerator
            else:  
                return emotional_Qgenerator
        
        # 初回質問の準備
        question_generator = get_current_question_generator()
        initial_context = f"""
        【現在のフェーズ】
        {session.current_phase}
        【現在のトピック】
        {session.current_topic}
        最初の質問を生成してください。
        """
        # initial_context = f"""
        # 【インタビューコンテキスト】
        # {context_summary}
        # 【現在のフェーズ】
        # {session.current_phase}
        # 【現在のトピック】
        # {session.current_topic}
        # 最初の質問を生成してください。
        # """
        interview_history_text=""
        initial_result,log_entry = await run_ai_with_logging(question_generator, initial_context, session)
        initial_question = initial_result.final_output_as(InterviewQuestion)
        current_question = initial_question.question

        # 質問ラウンドのループ
        for round_num in range(1, max_rounds + 1):
            remaining_minutes = session.get_remaining_time(time_limit_minutes)
            if remaining_minutes <= 0:
                await cl.Message("\n制限時間に達しました。インタビューを終了します。").send()
                break

            user_input=await cl.AskUserMessage(content=f"(Q{round_num}: {current_question}",timeout=108000).send()
            print(f"\n{session.current_phase}質問AI (Q{round_num}: {current_question}")
            answer =  user_input["output"]
            session.add_interview_qa(current_question, answer)
            for i, (q, a) in enumerate(session.interview_history):
                interview_history_text += f"Q{i+1}: {q}\nA{i+1}: {a}\n\n"

            # タイムアウトした場合は user_input が None
            if user_input is None or not answer:
                await cl.Message("\n入力の制限時間に達しました。インタビューを終了します。").send()
                break
            if trace_ai_communication:
                last_log = session.ai_communication_logs[-1]
                print(f"\n1AI通信トレース - {last_log.agent_name}:")
                print(f"  処理時間: {last_log.processing_time:.2f}秒")
                print("AI通信トレースが有効化されています\n")

            if answer.lower() in ["終了"]:
                print("\n インタビューを終了します。")
                return session
            
            # インタビュー管理AIによるアクション判断（回答分析なしの簡易版）
            manager_context = f"""
            【現在の状況】
            - 残り時間: {remaining_minutes:.1f}分
            - 進行ラウンド: {round_num}/{max_rounds}
            - 現在のフェーズ: {session.current_phase}
            - カバー済みトピック: {', '.join(session.covered_topics)}
            - 未カバートピック: {', '.join(session.topics_to_cover)}
            - 現在のトピック: {session.current_topic}
            
            【最新の質問と回答】
            質問: {current_question}
            回答: {answer}
            
            【これまでの会話履歴】
            {session.get_full_transcript()}
            
            【判断基準】
            回答の内容を分析して、以下の観点で深掘りが必要かを判断してください：
            1. 回答の具体性：抽象的すぎないか、具体例があるか
            2. 情報の完全性：数値、期間、頻度等の定量的情報があるか
            3. 深度：表面的でないか、背景や理由が説明されているか
            4. 業務マッチングに必要な情報：スキルレベル、経験の詳細、課題認識等が明確か
            
            次のアクションを決定してください。
            回答内容を見て、深掘りが必要か、次のトピックに進むべきか、
            フェーズを切り替えるべきか、ヒアリングを終了すべきかを判断してください。
            ただし同じような質問は二度行わないようにしてください。
            """
            # manager_context = f"""
            # 【インタビューコンテキスト】
            # {context_summary}
            # 【現在の状況】
            # - 残り時間: {remaining_minutes:.1f}分
            # - 進行ラウンド: {round_num}/{max_rounds}
            # - 現在のフェーズ: {session.current_phase}
            # - カバー済みトピック: {', '.join(session.covered_topics)}
            # - 未カバートピック: {', '.join(session.topics_to_cover)}
            # - 現在のトピック: {session.current_topic}
            # 【最新の質問と回答】
            # 質問: {current_question}
            # 回答: {answer}
            # 次のアクションを決定してください。
            # 回答内容を見て、深掘りが必要か、次のトピックに進むべきか、
            # フェーズを切り替えるべきか、インタビューを終了すべきかを判断してください。
            # ただし同じような質問は二度行わないようにしてください。
            # """
            manager_result,log_entry = await run_ai_with_logging(manager,manager_context, session)
            manager_action= manager_result.final_output_as(ManagerAction)
            if trace_ai_communication:
                last_log = session.ai_communication_logs[-1]
                print(f"\n2AI通信トレース - {last_log.agent_name}:")
                print(f"  処理時間: {last_log.processing_time:.2f}秒")
                print("AI通信トレースが有効化されています\n")
                x_manager+=last_log.processing_time
                
            # インタビュー管理AIアクションのログ記録
            session.add_manager_log(round_num, manager_action)

            # マインタビュー管理AIアクションに基づく処理
            print(f"\nインタビュー管理AI: {manager_action.message}")
            
            if manager_action.action_type == "end_interview" or round_num==max_rounds:
                print("\nインタビュー管理AI: インタビューを終了します。")
                print(f"指揮AIの出力時間合計:{x_manager}")
                break    
            elif manager_action.action_type == "switch_phase":
                # フェーズ切り替え
                if manager_action.next_phase and manager_action.next_phase in session.phases:
                    if session.switch_phase(manager_action.next_phase,session.phases,session.phase_topics):
                        print(f"\nフェーズを切り替えました: {session.current_phase}")
                        # 新フェーズの質問生成AIを取得
                        question_generator = get_current_question_generator()
                        # 新フェーズの最初の質問を生成
                        phase_context = f"""
                        【現在のフェーズ】
                        {session.current_phase}
                        【現在のトピック】
                        {session.current_topic}
                        【過去の質問と回答】
                        {session.get_full_transcript()}
                        【残り時間】
                        {remaining_minutes:.1f}分                        
                        {session.current_phase}の最初の質問を生成してください。
                        """
                        # phase_context = f"""
                        # 【インタビューコンテキスト】
                        # {context_summary}
                        # 【現在のフェーズ】
                        # {session.current_phase}
                        # 【現在のトピック】
                        # {session.current_topic}
                        # 【過去の質問と回答】
                        # {session.get_full_transcript()}
                        # 【残り時間】
                        # {remaining_minutes:.1f}分                        
                        # {session.current_phase}の最初の質問を生成してください。
                        # """
                        question_result,log_entry = await run_ai_with_logging(question_generator, phase_context)
                        interview_question = question_result.final_output_as(InterviewQuestion)
                        current_question = interview_question.question
            elif manager_action.action_type == "switch_topic":
                # トピック切り替え
                if session.current_topic:
                    session.mark_topic_covered(session.current_topic)
                session.set_current_topic(manager_action.next_topic)
                
                # 新トピックに対する質問生成
                question_generator = get_current_question_generator()
                topic_context = f"""
                【現在のフェーズ】
                {session.current_phase}
                【現在のトピック】
                {session.current_topic}
                【過去の質問と回答】
                {session.get_full_transcript()}  
                【残り時間】
                {remaining_minutes:.1f}
                新しいトピック「{session.current_topic}」について、最初の質問を生成してください。
                """
                # topic_context = f"""
                # 【インタビューコンテキスト】
                # {context_summary}
                # 【現在のフェーズ】
                # {session.current_phase}
                # 【現在のトピック】
                # {session.current_topic}
                # 【過去の質問と回答】
                # {session.get_full_transcript()}  
                # 【残り時間】
                # {remaining_minutes:.1f}
                # 新しいトピック「{session.current_topic}」について、最初の質問を生成してください。
                # """
                question_result,log_entry = await run_ai_with_logging(question_generator, topic_context)
                interview_question = question_result.final_output_as(InterviewQuestion)
                current_question = interview_question.question

            elif manager_action.action_type == "deep_dive":
                # 深掘り質問
                question_generator = get_current_question_generator()
                deep_dive_context = f"""
                【現在のフェーズ】
                {session.current_phase}
                【現在のトピック】
                {session.current_topic}
                【これまでの会話履歴】
                {session.get_full_transcript()}
                【直前の質問】
                {current_question}
                【回答】
                {answer}
                
                上記の回答をさらに深掘りする質問を生成してください。
                以下の観点で深掘りしてください：
                - 具体的な数値、期間、頻度を引き出す
                - 具体例や事例を求める
                - 背景や理由を詳しく聞く
                - 課題や改善点を探る
                - 感情や印象を掘り下げる
                
                回答者が詳しく語れるよう、オープンエンドな質問を心がけてください。
                """
                question_result,log_entry = await run_ai_with_logging(question_generator, deep_dive_context)
                interview_question = question_result.final_output_as(InterviewQuestion)
                current_question = interview_question.question
            # elif manager_action.action_type == "deep_dive":
            #     # 深掘り質問
            #     deep_dive_context = f"""
            #     【インタビューコンテキスト】
            #     {context_summary}
            #     【現在のフェーズ】
            #     {session.current_phase}
            #     【現在のトピック】
            #     {session.current_topic}
            #     【直前の質問】
            #     {current_question}
            #     【回答】
            #     {answer}
            #     上記の回答をさらに深掘りする質問を生成してください。
            #     具体的な数値や例を引き出す質問が望ましいです。"""
            #     question_generator = get_current_question_generator()
            #     question_result,log_entry = await run_ai_with_logging(question_generator, deep_dive_context)
            #     interview_question = question_result.final_output_as(InterviewQuestion)
            #     current_question = interview_question.question

            else:  # "next_question"
                # 通常の次の質問
                next_question_context = f"""
                【現在のフェーズ】
                {session.current_phase}
                【現在のトピック】
                {session.current_topic}
                【過去の質問と回答】
                {session.get_full_transcript()}
                【残り時間】
                {remaining_minutes:.1f}分
                次の質問を生成してください。
                過去に尋ねた質問と重複しないように注意してください。
                """
            # else:  # "next_question"
            #     # 通常の次の質問
            #     next_question_context = f"""
            #     【インタビューコンテキスト】
            #     {context_summary}
            #     【現在のフェーズ】
            #     {session.current_phase}
            #     【現在のトピック】
            #     {session.current_topic}
            #     【過去の質問と回答】
            #     {session.get_full_transcript()}
            #     【残り時間】
            #     {remaining_minutes:.1f}分
            #     次の質問を生成してください。
            #     過去に尋ねた質問と重複しないように注意してください。
            #     """
                question_generator = get_current_question_generator()
                question_result = await run_ai_with_logging(question_generator, next_question_context)
                interview_question = question_result.final_output_as(InterviewQuestion)
                current_question = interview_question.question
            cl.user_session.set("interview_history_text",interview_history_text)
        return True

    ##インタビュー全体を実行する関数
    async def run_interview(max_rounds: int, time_limit_minutes:int, trace_ai_communication=True):
        #インタビュー実行準備   デフォルト値があるものが最初にくるようにする
        email=cl.user_session.get("email")
        company_email=email.split("@")[1]
        session=cl.user_session.get("session")
        context_nurturinig=cl.user_session.get("context_nurturinig")
        #context_summary=cl.user_session.get("context_summary")
        cl.user_session.set("manager",create_manager(custom_prompts=None))
        cl.user_session.set("business_Qgenerator",create_business_Qgenerator(custom_prompts=None))
        cl.user_session.set("emotional_Qgenerator",create_emotional_Qgenerator(custom_prompts=None))
        cl.user_session.set("nurturing",create_nurturing(custom_prompts=None))
        #cl.user_session.set("summarizer",create_summarizer(custom_prompts=None))
        manager=cl.user_session.get("manager")
        business_Qgenerator=cl.user_session.get("business_Qgenerator")
        emotional_Qgenerator=cl.user_session.get("emotional_Qgenerator")
        nurturing=cl.user_session.get("nurturing")
        #summarizer=cl.user_session.get("summarizer")

        
        # ネイチャリングフェーズの実行
        if not session.phase_complete["nurting"]:
            nurturing_success = await run_nurturing_pahase(nurturing, session, context_nurturinig, trace_ai_communication=True)
            if not nurturing_success:
                print("\nネイチャリングフェーズで終了しました。")
                return session
            session.phase_complete["nurting"]=True
            
        #インタビューフェーズの実行
        if not session.phase_complete["interview"]:
            await run_interview_phase(manager, business_Qgenerator, emotional_Qgenerator, session,max_rounds, time_limit_minutes,trace_ai_communication=True)
            #await run_interview_phase(manager, business_Qgenerator, emotional_Qgenerator, session, context_summary,max_rounds, time_limit_minutes,trace_ai_communication=True)

        interview_history_text=cl.user_session.get("interview_history_text")
        nurturing_history_text=cl.user_session.get("nurturing_history_text")

        #db.collection(company_email).document("All-summary").set({"summary":final_all_summary.__dict__},merge=True)
        db.collection(company_email).document(email).set({"nurturing":nurturing_history_text,"interview":interview_history_text,"timestamp":firestore.SERVER_TIMESTAMP},merge=True)
        await cl.Message("インタビューはこれで終了になります。ご回答いただき、ありがとうございました。\nブラウザを閉じてください。").send()
        print("\nインタビューが完了しました。\n")


    await run_interview(max_rounds=30, trace_ai_communication=True,time_limit_minutes=30)