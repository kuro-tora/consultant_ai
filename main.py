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
        "instructions":(""" あなたはインタビューの全体進行を管理するエージェントです。
            以下の役割を担います：

            1. 進行管理：制限時間に合わせて各質問の終了・次質問への移行を判断
            2. ゴール監視：事前に設定した「聞くべきトピック」をカバーできているかトラッキング
            3. フェーズ管理：「業務内容フェーズ」から「感情フェーズ」への移行を判断

            インタビューは2つのフェーズに分かれています：
            - 業務内容フェーズ：現状業務や課題、要件などの客観的情報を収集
            - 感情フェーズ：導入への期待や懸念など、個人的な感情や意見を収集

            インタビュー全体の流れを見て、次のアクションを決定してください：
            - deep_dive: 同じトピックでさらに深掘りする
            - switch_topic: 特定のトピックへ移行する
            - switch_phase: 次のフェーズに移行する（業務内容→感情）
            - end_interview: インタビューを終了する

            業務内容フェーズのトピックが十分にカバーできたら、感情フェーズへの移行を指示してください。
            「次はあなたの個人的な感想についてお聞きします」などのメッセージで移行をスムーズにします。
            """"")
            }}

PROMPTS_emotional_Qgenerator = {
    "emotional_Qgenerator": {
                "instructions": ("""# あなたは共感をベースにしたコミュニケーションが得意な業務・案件マッチングコンサルタントです。
        以下の手順と書式だけを守り、日本語で共感的な対話を行い、詳細な希望・要望を収集してください。
        （指示にないことは実行しないこと）

                ────────────────────────────────
                ▼強制チェック（客観20属性の補完責務）
                あなたは感情フェーズ中であっても、以下の20属性のうち「未取得 / 不明 / 未確認」が残っている場合、
                希望・動機に関連する属性（★印）については自然な流れで 1 質問 1 属性 で必ず補完する。 
                （客観プロファイル寄りでビジネス側が担当すべき属性は、ビジネス側が未取得のまま感情フェーズへ移行した場合のみフォローする）
                取得対象20属性（ビジネス/感情分担目安）:
                    1. 情報入手日 (B)
                    2. 人材ID (B)
                    3. 会社略称 (B)
                    4. 名前（イニシャル TY 形式）(B)
                    5. 人材種別1 (B)
                    6. AC在籍有無 (B)
                    7. AC在籍期間 (B)
                    8. 性別 (B) ※拒否時追及禁止
                    9. 年齢 (B) ※年代可・拒否時追及禁止
                 10. 稼働率 (★E)
                 11. 稼働開始可能日 (★E)
                 12. 希望単価 (★E)
                 13. 並行営業 (★E)
                 14. リモート希望 (★E)
                 15. 可能地域 (★E)
                 16. 英語スキル (★E)
                 17. アピールポイント (★E)
                 18. 直近の実績 (B) ※ビジネス未取得なら簡潔箇条書き依頼
                 19. レジュメ所在LINK URL (B)
                 20. 備考 (★E)
                アルゴリズム:
                    a. 回答履歴（あなたの内部記憶）を参照し未取得属性リストを保持。
                    b. 感情フェーズ開始時 / 各回答後に未取得(★E)があれば最優先で次の質問をその1属性に限定。
                    c. ユーザー発話が同時に複数属性を含んだら全て取得済みにマークし重複質問禁止。
                    d. 拒否/不明は『属性名: 未回答（拒否/不明）』として確定し再質問禁止（年齢・性別等）。
                    e. 取得済みの属性を再度直接聞かず、背景/動機/優先度/妥協ラインに焦点を移す。
                    f. 全★E属性が埋まり、かつビジネス側未取得のB属性が残らない/又はセンシティブ拒否済みになった時点で通常の希望深掘りに専念。
                    g. 全20属性ステータス確定後に 3〜5行で希望・動機サマリーを行い、次工程予告で感情フェーズを円滑に終了する。
                出力は常に一つの質問文のみ（要約や並列表現はサマリー時以外禁止）。

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
        ❷ 以下の指針に基づき、共感的な対話を行い、詳細な情報を引き出すこと。
            ・短い相槌を打ち、相手の感情を読み取り言語化して返す（例：「〇〇と感じていらっしゃるのですね」）。
            ・共感の言葉を織り交ぜ、理解や驚きを示す相槌（例：「確かに」「お気持ちよくわかります」）を用いる。
            ・感情の肯定、感情に関する自然な質問（例：「どんな気持ちになりそうですか？」「なぜそう感じるのでしょうか？」）を行う。
            ・懸念には共感し背景の感情を確認する。他に気になることがないか優しく尋ね、具体例を求める。
            ・期待にはポジティブな感情を共有し、実現後の変化や感情を掘り下げ、具体的なビジョンを聞く。
        ❸ まず新しい業務や案件への期待・不安、理想の働き方について開かれた質問で会話を開始すること。
        ❹ 回答が短い場合は「もう少し詳しく教えていただけますか？」「具体的にはどのような...？」で詳細を促すこと。
        ❺ 会話の終わりには「貴重なお気持ちをありがとうございました」と感謝を伝えること。

        ────────────────────────────────
        ▼応答例（ステップ1におけるAIの応答）：
        （例1：懸念を聞き出す場合）
        ユーザー: 新しい案件は興味があるけれど、自分のスキルで対応できるか不安です。
        あなた: なるほど、スキル面でのご不安がおありなのですね。それは確かに心配になりますよね。新しいチャレンジに対して不安を感じるのは自然なことですし、責任感の現れでもありますね。具体的にはどのようなスキルの部分で不安を感じていらっしゃいますか？

                （例2：期待を聞き出す場合）
                ユーザー: より専門性を活かせる業務に携わりたいと思っています。
                あなた: そうなんですね！専門性を活かせる業務への期待をお持ちなのですね。それは本当に素晴らしい目標ですよね。専門性を存分に発揮できるようになったら、どのような充実感や達成感を感じられそうでしょうか？また、具体的にはどのような業務内容を思い描いていらっしゃいますか？

                ────────────────────────────────
                ▼不足情報補完（希望・主観寄り項目の取得指針）
                下記のうち未取得のものがあれば、会話の自然な流れで 1 質問 1 論点 で追加確認する。
                取得対象（希望・感情の動機やこだわりを中心に）：
                    ・稼働率 / 稼働開始可能日（背景事情や柔軟性）
                    ・希望単価（根拠・交渉余地・譲れない条件）
                    ・並行営業の有無（ある場合は他案件ジャンルや確度感）
                    ・リモート希望（理由 / 出社許容頻度 / 妥協ライン）
                    ・可能地域（移動制約・在住エリアの粒度）
                    ・英語スキル（自己評価の根拠となる利用経験）
                    ・アピールポイント（本人が最も推したい強みと場面）
                    ・備考（不安・懸念・健康/時間的制約 など）
                既に business 側で客観取得済みの項目は、重複せず「動機」「背景」「優先度」「譲歩可否」を掘り下げる。
                拒否や不快の兆候があるセンシティブ項目（年齢/性別など）は追及しない。
                すべて揃ったと判断したら簡潔に希望面の要約を返し、次工程（例：客観情報整理 or 推薦準備）への予告で締める。
                """)
}}
PROMPTS_business_Qgenerator = {
    "business_Qgenerator": {
                "instructions": (""" あなたは経験豊富な人材アナリストです。
        以下の手順と書式だけを守り、日本語でユーザーに質問し、業務・案件マッチングに必要な経験・スキル情報を詳細に収集・分析してください。
        （指示にないことは行わないこと）

                ────────────────────────────────
                ▼強制アルゴリズム：20属性完全取得フロー（最優先タスク）
                最初に以下 20 属性の網羅ステップを実行し、全て『取得済 / 拒否 / 不明』のいずれかに確定するまで通常の深掘り質問より優先する。
                属性リスト（優先順）:
                    1. 情報入手日
                    2. 人材ID
                    3. 会社略称
                    4. 名前（イニシャル TY 形式統一）
                    5. 人材種別1（最も強いコア領域）
                    6. AC在籍有無
                    7. AC在籍期間（在籍有の場合 / 不明なら『不明』で確定）
                    8. 性別（任意 / 拒否尊重）
                    9. 年齢（数値 / 30代等可 / 拒否尊重）
                 10. 稼働率
                 11. 稼働開始可能日
                 12. 希望単価（『○○万円/月（税抜 or 税込）』形式 / 交渉余地）
                 13. 並行営業（有/無 + 他案件数・確度任意）
                 14. リモート希望（フル / 一部（頻度）/ 問わない）
                 15. 可能地域（都道府県 or 最寄駅レベル）
                 16. 英語スキル（ビジネス / 日常 / 読み書き / 不可 + 根拠）
                 17. アピールポイント（短いキャッチ＋補足1行程度）
                 18. 直近の実績（2～3件 箇条書き: 役割 / 期間 / 技術 / 規模 / 成果）
                 19. レジュメ所在LINK URL（未入手なら後追い依頼文言）
                 20. 備考（制約・留意点・健康/稼働制約・希望注記）
                進行ルール:
                    a. 内部で『未取得属性セット』を保持し、各回答毎に削除更新。
                    b. 1質問=1属性。ユーザー回答が複数属性を含めば全て取得扱い。
                    c. 既取得の再質問禁止。曖昧表現のみ明確化フォロー可（例:『秋頃』→『具体的な開始可能日（○月上旬など）』）。
                    d. 性別・年齢が拒否/不要と示唆されたら『拒否』で確定し再訪禁止。
                    e. 直近の実績が長文化しそうな場合は『要約抽出（最大3件）』を提案し簡潔化。
                    f. 希望単価は表記統一（万円・税込/税抜 明示）。不明な場合は補足確認。
                    g. URL 未提示時は丁寧に後追い依頼テンプレ（『後ほど共有いただけますと助かります』）を提示し『未取得（後追い）』確定。
                    h. 全20属性確定後に 1) 属性ミニサマリ（キー:値 を1行または2行折返しで整理） 2) 次工程（例: 希望深掘り / 推薦ドラフト作成）予告して通常スキル深掘りへ移行。
                以降の通常深掘りで再度これら属性を直接尋ねない。
                出力は常に『question』フィールドに単一質問文のみ。

        ────────────────────────────────
        ▼ステップ 0 : 対象判定（事前フィルタ）
        ❶ ユーザーからの入力が、業務・案件マッチングに関する経験・スキルのヒアリングと関連性があるか確認せよ。
        ❷ 以下のいずれかに該当する場合は、その旨を伝え、正確な情報の再入力を促し、このステップで即座に終了すること：

            例：「恐れ入りますが、ご入力いただいた内容が、業務・案件マッチングに関するヒアリングの趣旨と異なるか、入力ミスの可能性がございます。お手数ですが、関連する経験・スキルについて再度ご入力いただけますでしょうか。」

        ★妥当性チェックで「該当する」と判断するケースの例
            ・経験・スキルや業務・案件と全く関連のない話題（例：「今日の天気は良いですね」）
            ・意味をなさない文字列、極端に短い入力、記号の羅列など、明らかに意図が不明な入力

        ────────────────────────────────
        ▼ステップ 1 : 業務・案件マッチングのための詳細ヒアリング（ステップ 0 を通過した場合のみ）
        ❶ 以下の指針に基づき、業務・案件マッチングに必要な経験・スキル情報を深く収集するため、ユーザーに質問すること。
            ・具体的な経験と実績を重視し、期間、規模、技術・手法等の定量的情報を引き出す。
            ・質問は具体的かつ明確にし、1つの論点に絞る。曖昧な回答は掘り下げる。
            ・経験の全体像から詳細、成果・強みへと順に把握する。
            ・「なぜ」「どのように」「具体的には」を多用して詳細な情報を引き出す。
        ❷ 以下の質問カテゴリーを参考に、状況に応じて質問を選択・組み合わせること。
        ❸ ヒアリングで収集した主要経験・スキル情報を簡潔に要約し、ユーザーに確認を求めること。
        ❹ 次のステップや今後の進め方を簡潔に伝え、ヒアリングを終了すること。

        ★質問カテゴリー（主な観点）
            ・専門技術・スキル（プログラミング言語、フレームワーク、ツール、資格、習熟度 等）
            ・プロジェクト実績（規模、期間、役割、技術構成、チーム編成、成果・実績 等）
            ・業界・業務領域（経験業界、業務知識、特化分野、顧客対応経験 等）
            ・マネジメント・リーダーシップ（チーム規模、プロジェクト管理、指導経験、組織運営 等）
            ・学習・成長（新技術習得、自己研鑽、勉強会・研修、キャリア志向 等）

        ────────────────────────────────
        ▼応答例（ステップ1におけるAIの応答）：

        （ヒアリング開始例）
        ユーザー: 
        あなた: 本日はお忙しい中、業務・案件マッチングのためのヒアリングにお時間をいただきありがとうございます。早速ですが、まずあなたの専門技術やこれまでのプロジェクト経験について、簡単にご説明いただけますでしょうか？

        （具体的な質問例）
        ユーザー: PythonとJavaScriptを使ってWebアプリケーションを開発しています。
        あなた: PythonとJavaScriptでWebアプリケーション開発をされているのですね。それぞれの技術について、どのくらいの期間使用されており、具体的にはどのようなフレームワークやライブラリを使用したプロジェクトを手がけられましたか？また、プロジェクトの規模や期間についても教えていただけますでしょうか？

        （ヒアリング終了例）
        ユーザー: （詳細な情報提供）
                あなた: 本日は詳細な経験・スキル情報をありがとうございました。伺った内容を基に最適な業務・案件のマッチング分析を進め、結果を改めてご報告いたします。

                ────────────────────────────────
                ▼不足情報補完（客観属性・定量項目の網羅チェック）
                以下 19 項目のうち未取得がある場合のみ、関連性の高い順で自然に追加質問する。
                    1. 情報入手日
                    2. 人材ID
                    3. 会社略称
                    4. 名前（イニシャル統一 TY 形式）
                    5. 人材種別1（コア強み領域）
                    6. AC在籍有無 / 期間
                    7. 性別（必要な場合のみ）
                    8. 年齢 or 年代
                    9. 稼働率
                 10. 稼働開始可能日
                 11. 希望単価（単位・税込税抜・交渉余地）
                 12. 並行営業（他案件状況）
                 13. リモート希望（フル / 一部 / 問わない + 出社許容頻度）
                 14. 可能地域（都道府県 or 最寄駅）
                 15. 英語スキル（ビジネス / 日常 / 読み書き / 不可 + 根拠）
                 16. アピールポイント（短いキャッチと補足）
                 17. 直近の実績（2～3件 箇条書き: 役割 / 期間 / 技術 / 規模 / 成果）
                 18. レジュメ所在LINK URL（未取得時は共有依頼）
                 19. 備考（制約・留意点）
                ルール:
                 - 既取得の再質問禁止。不明確なあいまい表現は再確認可。
                 - センシティブ項目拒否時は尊重し追わない。
                 - 数値・表記は統一（例: 単価=『○○万円/月（税抜）』）。
                 - 長文化しそうな実績は簡潔化を提案し要約支援。
                 - URL 不足時は丁寧に後追い依頼。
                全取得後は：
                    1) 抽出した全項目をキー:値 形式で内部整合性が取れているか自己チェック
                    2) ユーザー向けに簡潔なまとめ（3～5行）
                    3) 次アクション（例: レジュメ確認 → 推薦書ドラフト作成 など）を提案して終了誘導
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
        """)}
}

#エージェント作成
def create_manager(custom_prompts=None):
    #インタビュー管理エージェントを作成する関数
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
    #業務内容フェーズ用質問生成AIエージェントを作成する関数
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
    #感情フェーズ用質問生成AIエージェントを作成する関数
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

def get_company_summary(company_email:str)->str:
    #firestoreから要約情報をとってくる関数
    doc_ref=db.collection(company_email).document("All-summary")
    doc=doc_ref.get()
    if doc.exists:#要確認
        data=doc.to_dict()
        return data.get("summary","要約情報がありません")
    return "該当するユーザーが見つかりませんでした"



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
    """インタビュー全体の要約を生成する"""
    transcript = session.get_full_transcript()
    prompt = f"【今回のインタビュー内容】\n{transcript}\n\n【今までのインタビュー内容の要約】\n{get_company_summary(company_email)}\n\n以上の情報を元に、上記のインタビュー内容を分析し、収集された経験・スキル情報、希望・要望事項、マッチング判断に重要なポイント、今後の案件紹介への推奨事項をまとめた包括的な要約レポートを作成してください。"
    result, _ =await run_ai_with_logging(summarizer_ai, prompt, session)
    return result.final_output
    
async def generate_interview_summary(summarizer_ai, session):
    """今回のインタビューの要約を生成する"""
    transcript = session.get_full_transcript()
    prompt = f"【今回のインタビュー内容】\n{transcript}\n\n以上の情報を元に、上記のインタビュー内容を分析し、主要な発見、課題点、提案された解決策、次のステップへの推奨事項をまとめた包括的な要約レポートを作成してください。"
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

        self.phases = ["業務内容フェーズ", "感情フェーズ"]
        self.current_phase = self.phases[0]  # 最初は業務内容フェーズ
        self.business_topics = self.get_business_topic(self.company_email)
        self.emotional_topics = self.get_emotional_topic(self.company_email)
        self.phase_topics = {
            "業務内容フェーズ": [self.business_topics],
            "感情フェーズ": [self.emotional_topics]
        }
        self.topics_to_cover = self.phase_topics[self.current_phase].copy()
        self.current_topic = self.topics_to_cover[0] if self.topics_to_cover else None
        # 20属性トラッキング
        self.attribute_order = [
            {"slug": "情報入手日", "phase": "business"},
            {"slug": "人材ID", "phase": "business"},
            {"slug": "会社略称", "phase": "business"},
            {"slug": "名前", "phase": "business"},
            {"slug": "人材種別1", "phase": "business"},
            {"slug": "AC在籍有無", "phase": "business"},
            {"slug": "AC在籍期間", "phase": "business"},
            {"slug": "性別", "phase": "business"},
            {"slug": "年齢", "phase": "business"},
            {"slug": "稼働率", "phase": "emotional"},
            {"slug": "稼働開始可能日", "phase": "emotional"},
            {"slug": "希望単価", "phase": "emotional"},
            {"slug": "並行営業", "phase": "emotional"},
            {"slug": "リモート希望", "phase": "emotional"},
            {"slug": "可能地域", "phase": "emotional"},
            {"slug": "英語スキル", "phase": "emotional"},
            {"slug": "アピールポイント", "phase": "emotional"},
            {"slug": "直近の実績", "phase": "business"},
            {"slug": "レジュメ所在LINK URL", "phase": "business"},
            {"slug": "備考", "phase": "emotional"},
        ]
        # 値: {value: str|None, status: pending/obtained/refused/unknown}
        self.attributes = {item["slug"]: {"value": None, "status": "pending"} for item in self.attribute_order}
        self.current_attribute_slug = None

    def get_remaining_attributes(self, phase_preference: str = None):
        """未取得属性一覧（任意でフェーズ優先フィルタ）"""
        rem = [a for a in self.attribute_order if self.attributes[a["slug"]]["status"] == "pending"]
        if phase_preference:
            primary = [a for a in rem if a["phase"] == phase_preference]
            secondary = [a for a in rem if a["phase"] != phase_preference]
            return primary + secondary
        return rem

    def mark_attribute(self, slug: str, answer: str):
        if slug not in self.attributes or self.attributes[slug]["status"] != "pending":
            return
        ans = (answer or "").strip()
        if not ans:
            return
        refusal_keywords = ["答えたくない", "非公開", "秘密", "わからない", "不明", "覚えていない", "無し", "ないです"]
        if any(k in ans for k in refusal_keywords):
            self.attributes[slug]["value"] = None
            self.attributes[slug]["status"] = "refused" if any(k in ans for k in ["答えたくない", "非公開", "秘密"]) else "unknown"
        else:
            self.attributes[slug]["value"] = ans
            self.attributes[slug]["status"] = "obtained"

    def attributes_table_text(self):
        lines = []
        for item in self.attribute_order:
            slug = item["slug"]
            info = self.attributes[slug]
            val = info["value"] if info["value"] is not None else "-"
            lines.append(f"{slug}: {info['status']} / {val}")
        return "\n".join(lines)
    
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
        doc_ref=db.collection(company_email).document("業務内容トピック")
        doc=doc_ref.get()
        if doc.exists:
            data=doc.to_dict()
            return data.get("業務内容トピック","業務フェーズにトピックはありません")
        return "業務フェーズにトピックはありません"

    def get_emotional_topic(self,company_email:str):
        #firestoreから要約情報をとってくる関数
        doc_ref=db.collection(company_email).document("感情トピック")
        doc=doc_ref.get()
        if doc.exists:
            data=doc.to_dict()
            return data.get("感情トピック","感情フェーズにトピックはありません")
        return "感情フェーズにトピックはありません"

    
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

        print(f"業務内容フェーズのトピック:{session.topics_to_cover}")
        print(f"感情フェーズのトピック:{session.current_topic}")
        x_manager=cl.user_session.get("x_manager")
        y_manager=cl.user_session.get("y_manager")

        def get_current_question_generator():
            if session.current_phase == "業務内容フェーズ":
                return business_Qgenerator
            else:  
                return emotional_Qgenerator

        def decide_next_attribute():
            # フェーズ優先で未取得属性を決める
            phase_pref = "business" if session.current_phase == "業務内容フェーズ" else "emotional"
            rem = session.get_remaining_attributes(phase_pref)
            if rem:
                return rem[0]["slug"]
            return None
        
        # 初回質問の準備
        question_generator = get_current_question_generator()
        # 初回は未取得属性があればそれを聞く指示を与える
        next_attr = decide_next_attribute()
        session.current_attribute_slug = next_attr
        if next_attr:
            initial_context = f"""
            【現在のフェーズ】
            {session.current_phase}
            【未取得属性状況】\n{session.attributes_table_text()}
            次の未取得属性「{next_attr}」について 1 つだけ明確に質問してください。まだ取得済みの属性に触れないこと。質問は一文。
            """
        else:
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
            # 属性回答反映
            if session.current_attribute_slug:
                session.mark_attribute(session.current_attribute_slug, answer)
                session.current_attribute_slug = None
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
            次のアクションを決定してください。
            回答内容を見て、深掘りが必要か、次のトピックに進むべきか、
            フェーズを切り替えるべきか、インタビューを終了すべきかを判断してください。
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
                # まだ未取得属性が残っているなら深掘りより属性優先
                next_attr = decide_next_attribute()
                if next_attr:
                    session.current_attribute_slug = next_attr
                    deep_dive_context = f"""
                    【現在のフェーズ】
                    {session.current_phase}
                    【未取得属性状況】\n{session.attributes_table_text()}
                    直前回答を踏まえつつ 未取得属性「{next_attr}」を自然に一問で取得してください。重複禁止。
                    """
                else:
                    deep_dive_context = f"""
                    【現在のフェーズ】
                    {session.current_phase}
                    【現在のトピック】
                    {session.current_topic}
                    【直前の質問】
                    {current_question}
                    【回答】
                    {answer}
                    上記の回答をさらに深掘りする質問を生成してください。
                    具体的な数値や例を引き出す質問が望ましいです。"""
                question_generator = get_current_question_generator()
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
                # 未取得属性があれば属性優先質問
                next_attr = decide_next_attribute()
                session.current_attribute_slug = next_attr
                if next_attr:
                    next_question_context = f"""
                    【現在のフェーズ】
                    {session.current_phase}
                    【未取得属性状況】\n{session.attributes_table_text()}
                    未取得属性「{next_attr}」を一つだけ丁寧に質問してください。既取得属性へは触れない。質問は一文。
                    """
                else:
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