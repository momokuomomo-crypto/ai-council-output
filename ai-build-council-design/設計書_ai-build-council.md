# ai-build-council 設計書

Version: 1.0.0

---

# 1. 目的

要件定義（[要件定義_ai-build-council.md](要件定義_ai-build-council.md)）で
定めたワークフローを、実際にClaude Codeスキルとして実装可能な粒度まで
落とし込む。

---

# 2. 全体フロー

```text
0. Intake・隔離・予算設定
      │
      ▼
1. 独立設計（Codex, 新規セッション, read-only）
      │
      ▼
2. 設計査読・凍結（Claude査読, isolated, 上限2ラウンド）
      │
      ▼
3. 実装（議長Fable本体、workspace-write許可はここのみ）
      │
      ▼
4. Test Gate A（上限5回、早期停止条件あり）
      │
      ▼
5. 固定diffの独立実装レビュー（Codex 新規セッション + Claude査読）
      │
      ▼
6. 指摘処理（Fixed/WontFix/Disputed）・Test Gate B
      │
      ▼
7. 成果確定・commit・push・記録（事前承認ゲート）
      │
      ▼
   人がレビュー・採否判断
```

---

# 3. ディレクトリ構成

```text
.claude/
└─ skills/
   └─ ai-build-council/
      ├─ SKILL.md                       # スキル本体（動作の正）
      ├─ models.md                      # 各席のモデル・権限・禁止事項
      ├─ references/
      │  ├─ workflow.md                 # 本設計書の要約（実行時参照用）
      │  ├─ decision-policy.md          # Fixed/WontFix/Disputed運用ルール
      │  ├─ review-policy.md            # レビュー評価軸の優先順位
      │  ├─ git-policy.md               # commit/push/Issue運用ルール
      │  └─ codex-cli-robustness.md     # タイムアウト・リトライ仕様
      └─ templates/
         ├─ intake-template.md
         ├─ design-template.md
         ├─ design-review-template.md
         ├─ implementation-review-template.md
         ├─ dispute-template.md
         └─ final-report-template.md

<対象リポジトリ>/
└─ .ai-build-council/                   # 実行時の作業ディレクトリ（.gitignore対象）
   └─ runs/
      └─ <run-id>/
         ├─ state.json                  # 状態管理
         ├─ inputs/                     # user_requirements / reference_proposals / verified_repo_facts
         ├─ design/                     # Stage1の出力
         ├─ review/
         │  ├─ design-review/           # Stage2
         │  └─ implementation-review/   # Stage5（input.patch含む）
         ├─ tests/
         │  ├─ gate-a/                  # 生ログ
         │  └─ gate-b/
         ├─ decisions/                  # Fixed/WontFix/Disputed記録
         └─ final/                      # Stage7の最終報告・GitHub投稿ドラフト
```

`.ai-build-council/runs/`は原則gitignoreする。最終的に必要な要約だけを
`docs/ai-build-council-runs/<run-id>.md`としてcommitする（生ログに機密が
含まれ得るため、無条件commitは禁止）。

---

# 4. models.md の設計

```yaml
design:
  codex:
    command: codex exec
    sandbox: read-only
    session: new              # Stage5とは必ず別セッション
    stdin: /dev/null
    timeout_seconds: 600
    may_edit: false

design_review:
  claude_subagent:
    context: isolated
    may_edit: false
    may_see_codex_design: true
    max_rounds: 2

implementation:
  fable_main:
    may_edit: true
    may_run_bash: true
    sandbox: workspace-write   # このロールにのみ許可

implementation_review:
  codex:
    command: codex exec
    sandbox: read-only
    session: new               # design.codexと同一セッションを絶対に使わない
    stdin: /dev/null
    timeout_seconds: 600
    may_edit: false
    may_see_other_reviews: false
    review_axis_priority:
      - functional_correctness
      - security_and_data_loss_risk
      - error_handling_and_edge_cases
      - test_adequacy
      - maintainability
      - design_deviation   # 最下位。差異自体は欠陥として扱わない
  claude_subagent:
    context: isolated
    may_edit: false
    may_see_other_reviews: false

excluded:
  - gemini

grok_third_opinion:
  enabled: false   # ai-council_v2と同様、任意・既定無効・従量課金
```

---

# 5. 状態管理（state.json）

```json
{
  "run_id": "20260720-voice-tab-controller",
  "status": "IMPLEMENTING",
  "base_commit": "abc123",
  "candidate_commit": null,
  "design_revision": 1,
  "test_gate_a": {"status": "PENDING", "attempts": 0},
  "test_gate_b": {"status": "PENDING", "attempts": 0},
  "review_diff_hash": null,
  "open_blockers": [],
  "disputes": {},
  "budget": {
    "max_gate_attempts": 5,
    "max_dispute_rounds": 3,
    "time_limit_hours": null
  }
}
```

許可する状態遷移：

```text
INTAKE → DESIGNED → DESIGN_APPROVED → IMPLEMENTING
  → TEST_A_PASSED → REVIEWED → FIXING | TEST_B_PENDING
  → TEST_B_PASSED → READY_TO_COMMIT → COMMITTED → PUSHED → RECORDED
```

失敗したテストが残る状態から`READY_TO_COMMIT`へ進むことは禁止する。

---

# 6. Codex CLI呼び出し例

## 6.1 Stage 1（独立設計）

```bash
timeout 600 codex exec \
  --sandbox read-only \
  --skip-git-repo-check \
  "$(cat design-prompt.md)" \
  < /dev/null > ".ai-build-council/runs/$RUN_ID/design/codex.md" 2>&1
```

## 6.2 Stage 5（固定diffの独立実装レビュー、Stage1とは別セッション）

```bash
git diff --binary --no-ext-diff HEAD > \
  ".ai-build-council/runs/$RUN_ID/review/implementation-review/input.patch"
sha256sum ".ai-build-council/runs/$RUN_ID/review/implementation-review/input.patch"

timeout 600 codex exec \
  --sandbox read-only \
  --skip-git-repo-check \
  "$(cat implementation-review-prompt.md)" \
  < /dev/null > ".ai-build-council/runs/$RUN_ID/review/implementation-review/codex.md" 2>&1
```

## 6.3 ハング検知・リトライ（全呼び出し共通）

* `timeout 600`で強制終了させたうえで、出力ファイルが空または想定
  バナー（`OpenAI Codex`等）が一定時間（目安3分）出ない場合はハング
  候補と判定する
* ハング候補と判定したら、プロセスをkillしたうえで1回だけ同一コマンドを
  再実行する
* 再度ハングした場合は「環境障害」としてカウントし、Test Gate等の
  早期停止条件に含める（無制限リトライはしない）

---

# 7. commit・push・Issue記録の運用

```bash
# commit（対象ファイルを明示。git add . は禁止）
git add -- <明示したファイル一覧>
git diff --cached --check
git commit -m "<メッセージ>"

# push（事前に人間が「完了時にpushしてよい」と明示許可した場合のみ）
git push -u origin "<branch>"

# Issue記録（pushと同等のゲート。対象リポジトリを明示パラメータに）
gh issue comment "$ISSUE_NUMBER" --repo "<owner>/<repo>" \
  --body-file ".ai-build-council/runs/$RUN_ID/final/github-comment.md"
```

承認がない場合は、`final/github-comment.md`等のドラフト生成に留め、
実際の投稿・pushは行わない。

---

# 8. Chrome拡張機能（音声タブコントローラー）での検証結果

具体例として検証した結果、以下が要件・設計に反映されている。

## 8.1 設計上の要点

* Manifest V3、`tabs`・`storage`・`action`権限
* `tabs.Tab.audible`で音声再生中タブを識別、`tabs.update(tabId, {muted: true})`
  でミュート、`storage.sync`へサイト規則を保存
* 一覧表示は最低3状態を区別する：
  `audible=true,muted=false`（現在聞こえる）／
  `audible=true,muted=true`（再生中だがミュート済み）／
  `audible=false,muted=true`（ミュート済みだが現在は無音）
* 「一括ミュート」に対応する一括解除では、拡張自身が変更したタブIDを
  追跡し、ユーザーが元々ミュートしていたタブを誤って解除しない

## 8.2 テスト構成（コア実装とハーネス構築の見積もりを分離）

```text
Gate A
  lint / typecheck / 単体テスト（chrome API mock）/ build

実装レビュー

Gate B
  Gate A再実行 + 回帰テスト + 実Chromeスモークテスト
```

実Chrome検証シナリオ（例）：拡張ロード、無音タブが一覧に出ない、
音声再生で一覧に現れる、個別ミュートで実際に音が止まる、一括ミュート、
サイト常時ミュートの新規タブへの自動適用、service worker再起動後の
永続性、規則削除後に自動ミュートされない、等。

見積もり：コア実装 5〜7時間（元の想定どおり）＋ テストハーネス構築
（chrome API mock環境・実Chrome E2E環境の初期整備）は別枠。ハーネスは
一度整備すれば以後の拡張機能でも再利用できるため、2件目以降は
このコストが下がる想定。

---

# 9. ai-council_v2との関係（実装上の注意）

* ai-build-councilのコード・スキルは、ai-council_v2のリポジトリ・
  スキルディレクトリを一切参照・呼び出さない
* ai-council_v2の成果物（要件定義・稟議書等）を参考にする場合は、
  ファイルパスまたはURLとして`reference_proposals`に人間が手動で
  渡す（自動連携はしない）

---

# 10. 未確定・今後の検討事項

* `WontFix`と`Disputed`の人間裁定を、誰がどの期限で行うかの運用ルール
* 人間が応答しない場合の安全な終了・保存方法
* Test Gate A/Bの試行上限・時間上限・コスト上限の案件ごとの調整方法
* Chrome拡張以外の言語・フレームワークでのGate A/B構成（今回はNode.js/
  Chrome拡張を前提に検討したため、他言語での一般化は次の案件で検証する）
