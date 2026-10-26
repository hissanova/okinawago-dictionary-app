# デプロイ・運用ガイド

この文書のGCPコマンドは運用担当者が導入・復旧時に実行するものです。実装時にはGCPへの接続、バケット・IAM・トリガーの変更、実デプロイは行っていません。GCP上での動作は未検証です。プレースホルダー（`STATE_BUCKET`、`BUILD_ID`、`OLD_REVISION`など）は確認した実値に置き換えてください。CLI例はfishでも実行できる構文です。

## 対象と構成

| 項目 | 固定値 |
| --- | --- |
| GitHub | `hissanova/okinawago-dictionary-app`、main |
| GCPプロジェクト | `okinawago-dictionary` |
| Cloud Run | `okinawago-dictionary-app` / `asia-southeast1` |
| 公開サイト | https://okinawago.app |
| イメージ保存先 | `asia.gcr.io/okinawago-dictionary/okinawago-dictionary-app/okinawago-dictionary-app` |
| 本番トリガー | `166433e9-9b3d-4554-b92d-0d8c4e2aceb3` / `global` |
| 廃止するビルド専用トリガー | `5127d15f-b34a-4066-9956-da3b828b207a` / `asia-east1` |
| SECRET_KEY参照 | Secret Manager `okinawago-flask-secret-key` バージョン `1` |

[cloudbuild.release.yaml](../cloudbuild.release.yaml)を本番トリガーから明示的に選択します。ルートの `cloudbuild.yaml` は置きません。これにより、既存の自動検出トリガーが新設定を意図せず選ぶことを防ぎます。

処理はアプリイメージのビルド1回 → 同じローカルイメージのunittest・Gunicorn HTTP確認 → push → レジストリでdigest確定・pushしたイメージのRepoDigestsと照合 → 排他ロック → 新リビジョン配置 → 専用URL確認 → 明示したリビジョンへ100%切り替え、の順です。各ステップは前段の成功が必要です。テストしたイメージを再ビルドしません。Docker CLIは公式Dockerビルダーから共有ディレクトリへコピーし、Python / gcloudには公式CLIのslimイメージを使用します。

タグは `COMMIT_SHA-BUILD_ID` で追跡でき、配置はタグでなく `保存先@sha256:...` を使います。Cloud Buildの実行情報を読み、プロジェクト・ビルドID・本番トリガーID・mainブランチ・コミットSHAを照合します。配置時には `--update-labels` で `commit-sha`、`gcb-build-id`、`gcb-trigger-id` を今回の値へ更新し、無関係な既存ラベルを維持します。これらは直近の配置を示すため、検証中には本番送客先と異なる場合があります。送客先はtrafficと記録で確認します。トリガーはmainへのpushのみを対象にし、古いコミットの手動再実行を自動反映用途で使わないでください。

配置は既存サービスの存在確認後に `gcloud run services update` を使います。別サービスを新規作成しません。`--no-traffic` と、完全なビルドID＋試行IDを入力にしたSHA-256由来の名前を指定します。検証用タグは `p`＋ハッシュ20桁（21文字）、リビジョン接尾辞は `r`＋ハッシュ32桁（33文字）と別々に生成します。タグには `len(サービス名) + len(タグ) <= 46`、リビジョン名全体には63文字以下という別の制限があり、本サービスではそれぞれ45文字・58文字です。完全なビルドID・試行IDと生成したタグ・接尾辞・リビジョン名を同じ記録に保存し、短い名前からも実行を追跡できます。タグが既存のものと衝突した場合は再利用せず中断します。配置した名前のリビジョンがReadyであること、所属サービス、imageDigest、専用タグのリビジョン名とURL、既存SECRET_KEY参照を照合します。`latestReadyRevisionName` だけで対象を決定しません。

専用URLで [scripts/smoke_http.py](../scripts/smoke_http.py) によるCSRF・Cookie付き検索と3辞書の詳細本文を検証し、検証後に対応関係と本番トラフィックが変わっていないことを再確認します。成功時のみ `--to-revisions=検証済みリビジョン=100` で切り替え、切り替え後の割当も確認します。`--to-latest` は使いません。IAM・公開範囲・環境変数・シークレット・実行サービスアカウントを変更するフラグは渡しません。

## 必要なツール・権限・バケット

運用端末にはPython 3.10以上、Google Cloud CLI、バックアップを安全に保管する場所が必要です。Dockerによる事前確認には[開発ガイド](development.md)のツールも用意します。Cloud Build側は公式DockerビルダーとGoogle Cloud CLIイメージを利用します。Cloud Build / Cloud Run / Storage / 使用中レジストリに必要なAPIが有効であること、gcr.io保存先が現在のArtifact Registry移行状態でも読み書きできることを担当者が確認します。

状態・記録専用の既存Cloud Storageバケットを、導入担当者が事前に用意します（例: `okinawago-dictionary-release-state`。名前の空きは未確認）。非公開、均一なバケットレベルのアクセス制御、適切なリージョンを選択してください。`release/state.json` を自動削除するLifecycleや保持期限を設定しないでください。ロックと順序情報を削除・初期化すると古い反映を防ぐ根拠を失います。記録の保存期間は運用側で決め、状態ファイルには適用しません。オブジェクトバージョニングは復旧時の監査に有用です。

| 主体・対象 | 必要な権限と範囲 |
| --- | --- |
| Cloud Buildの実行アカウント / 状態バケット | `storage.objects.get`、`storage.objects.create`、`storage.objects.delete`（同名オブジェクトの条件付き上書きに必要）。専用バケットのみに限定したカスタムロール、または同範囲の権限を確認。アプリはオブジェクト削除APIを呼ばない |
| 同アカウント / Cloud Build | `cloudbuild.builds.get`（自分のcreateTime・source確認）。既存のログ書き込み権限も維持 |
| 同アカウント / 既存Cloud Run | `run.services.get`、`run.services.update`、`run.revisions.get`、`run.operations.get`。`roles/run.developer`を参考に既存サービスへ限定。サービス新規作成・IAM変更権限はこの処理には不要 |
| 同アカウント / 既存実行アカウント | 配置に必要な `iam.serviceAccounts.actAs` を実際のCloud Run実行アカウントだけに限定して確認 |
| 同アカウント / 既存レジストリ | 対象保存先へのイメージpush・メタデータread。Artifact Registryへ移行済みなら対象リポジトリのWriter相当など、実構成に合わせて確認 |
| Cloud Run実行アカウント / 既存シークレット | バージョン1を読める既存のSecret Accessor等を維持。Cloud Buildにシークレットの値を読む権限は追加しない |
| 移行・復旧担当者 | トリガーの閲覧・更新・実行、ビルド状態閲覧、必要時のキャンセル、Cloud Runの閲覧・traffic更新、状態バケットの読み取り・世代条件付き上書き。既存組織ポリシーに従う |

トリガーにCloud Buildのサービスアカウントは明示指定されていません。画面に案内される `429157770916@cloudbuild.gserviceaccount.com` は従来のビルド用アカウントです。実際のビルド詳細の `serviceAccount` と照合し、Cloud Runの実行アカウント（サービステンプレートの `serviceAccountName`）と区別します。権限は推測して付け足さず、IAM担当者が現状と必要な差分を確認してください。このリポジトリにはIAM変更やバケット作成処理を含めません。

## 排他制御・反映順序・記録

状態ファイル `gs://STATE_BUCKET/release/state.json` にスキーマversion、owner（ビルドID・試行ID）、watermark（切り替えを試みた順序）、last_promoted（最後に切り替えを確認した記録）を保存します。初回だけ `ifGenerationMatch=0` で作成し、以後は読んだ世代番号を条件に更新します。内容の読み取りも同じ世代に固定します。ownerが空の時だけ取得でき、解放は自分のownerと世代を照合してownerを空にする更新です。オブジェクト自体は削除しません。[GCSの世代条件](https://docs.cloud.google.com/storage/docs/request-preconditions)を使用します。

ロック待ちは最大300秒です。新版の配置から確認・切り替え・自分のタグ削除まで保護します。順序はCloud Buildサーバーの `createTime`（ナノ秒へ正規化）とビルドIDの組です。新しいビルドの反映後に遅れてロックを得た古いビルドは、配置前に `superseded` として終了します。同一時刻はIDで順序を確定します。コミットの祖先関係を調べる方式ではありません。

外部のtraffic更新とGCS更新は単一トランザクションにできないため、切り替え直前にwatermarkを永続化します。切り替え失敗でもこの保守的な順序境界は戻しません。結果不明の更新が実際には反映されていても、後から古いビルドを反映させないためです。`_PROMOTE=false` の確認実行はwatermarkやlast_promotedを進めません。

記録は `release/records/BUILD_ID/ATTEMPT.json` とCloud Buildログに残します。コミットSHA、ビルドID・リージョン、本番トリガーID、digest、配置予定・実際に照合したリビジョン、タグ・専用URL、切り替え前の全traffic割当、段階・失敗理由・後片付け結果を保存します。失敗した配置では予定リビジョンが存在しない場合があります。配置前の記録に失敗したら配置を始めません。Secret値やサービス設定全体をログには出しません。

既存Inlineトリガーや手作業での更新はこのロックに参加しません。必ず移行時に停止してください。復旧・切り戻し時も、トリガー停止と実行中ビルドの確認を先に行います。ロックを使わない外部操作との並行更新までは保証できません。

## 初回移行

### 1. バックアップ

作業ディレクトリをリポジトリ外に作り、両トリガーの完全な設定（Inline YAMLを含む）とCloud Runの既存設定を保存します。以下はシークレット値を取得しません。サービス定義には他の環境変数が含まれ得るため、ファイルは担当者だけが読める場所で扱ってください。

```sh
mkdir -p /tmp/okinawago-deploy-backup
chmod 700 /tmp/okinawago-deploy-backup
gcloud builds triggers describe 166433e9-9b3d-4554-b92d-0d8c4e2aceb3 --project=okinawago-dictionary --region=global --format=json > /tmp/okinawago-deploy-backup/production-trigger.json
gcloud builds triggers describe 5127d15f-b34a-4066-9956-da3b828b207a --project=okinawago-dictionary --region=asia-east1 --format=json > /tmp/okinawago-deploy-backup/build-only-trigger.json
gcloud run services describe okinawago-dictionary-app --project=okinawago-dictionary --region=asia-southeast1 --format=json > /tmp/okinawago-deploy-backup/service.json
```

現在のトリガーイベント・ブランチ条件・置換変数・serviceAccount・公開範囲・SECRET_KEY参照が想定通りであることを確認します。既存Inlineの `build` フィールドは特に退避します。Secret Managerのaccessコマンドは実行しません。バックアップは `/tmp` だけに頼らず、保護された運用保管先にも保存してください。

### 2. 両トリガーを一時停止し、既存ビルドを待つ

Google Cloud Console → Cloud Build → トリガーでプロジェクトを選び、リージョンglobalの本番トリガーを **無効化**。続いてasia-east1のビルド専用トリガーも **無効化** します。削除はしません。停止後、以下とConsoleの履歴で実行中・待機中のビルドを確認します。

```sh
gcloud builds list --project=okinawago-dictionary --region=global --filter='status:(PENDING QUEUED WORKING)' --format='table(id,status,buildTriggerId,createTime)'
gcloud builds list --project=okinawago-dictionary --region=asia-east1 --filter='status:(PENDING QUEUED WORKING)' --format='table(id,status,buildTriggerId,createTime)'
```

トリガー無効化だけでは開始済みビルドを停止できません。両トリガーに属するものがすべて終わり、Cloud Runにも更新中の操作がないことを確認します。キャンセルした場合も、Cloud Runの操作完了と現在のtrafficを確認してから進めます。

### 3. バケットと権限を確認し、本番トリガーの設定を変更

先述の専用バケットと実際のビルド用アカウントの権限を担当者が用意・確認します。停止中の本番トリガーを編集し、次を設定します。

- リポジトリ: `hissanova/okinawago-dictionary-app`、push対象ブランチ: `^main$`
- 構成タイプ: Cloud Build構成ファイル、場所: **Repository**、パス: **`cloudbuild.release.yaml`**。既存Inlineは外す
- 置換変数: `_STATE_BUCKET=実際の専用バケット名`、`_BUILD_REGION=global`、**`_PROMOTE=false`**
- 実行アカウントやそれ以外のトリガー設定は現状を確認して維持

mainにこの設定ファイルとスクリプトが存在することを確認してから切り替えてください（コミット・マージは別途レビュー手続きで行う）。無効化したまま保存し、再度 `triggers describe` で `filename`、置換変数、main条件、停止状態を照合します。ビルド専用トリガーは以後も無効のままにし、二重build/pushを止めます。

### 4. 初回は切り替えなしで実行

本番トリガーだけを有効化してmainを手動実行します。確認中はmainへの更新を止め、Consoleの実行画面でも `_PROMOTE=false` を確認してください。

```sh
gcloud builds triggers run 166433e9-9b3d-4554-b92d-0d8c4e2aceb3 --project=okinawago-dictionary --region=global --branch=main
```

ログ・GCS記録で `verified_without_promotion`、3辞書のHTTP確認成功、実リビジョン・digest・専用URLの一致、旧traffic維持、`cleanup=complete`、ownerが空であることを確認します。専用タグは終了時に削除されるため、記録のURLは以後アクセスできないことがあります。初回は本番へ切り替えなくても新リビジョンが作られます。Consoleで実際のビルド用アカウント・既存SECRET_KEY参照・Cloud Run実行アカウント・公開範囲に変更がないことも確認します。

### 5. 自動切り替えを有効にする

初回記録をレビュー後、本番トリガーを一時停止し、実行中ビルドがないことを確認して、置換変数を **`_PROMOTE=true`** に変更します。設定を読み直して確認し、本番トリガーだけ再有効化します。mainで新しいビルドを実行し、`promoted` と実traffic、公開ドメインを確認します。初回の確認済みビルド自体を後から切り替える操作はせず、毎回そのビルドの同一イメージを配置・検証します。

### 移行失敗時に旧設定へ戻す

両トリガーを無効化し、実行中ビルド・Cloud Run操作の終了を確認します。新しい記録・ロック・trafficを調べ、必要なら下記の切り戻しを先に実施します。Cloud Build Consoleで本番トリガーを編集し、バックアップの `build` に保存したInline設定、元の置換変数・イベント・実行アカウントを復元します。元の自動検出設定や有効状態はbuild-onlyのバックアップでも確認します。保存後にJSONを再取得して比較してください。バックアップから新規トリガーを作成して二重起動させないよう、既存IDを編集します。

**Inline設定を復元するだけでは、旧方式の新版への自動送客は復旧しません。** `--no-traffic` はlatest追従を既存リビジョンへの固定割当に変えるため、その後に旧Inlineの `services update --image=...` を実行しても固定先が維持されます。旧方式の送客動作まで戻すには、以下の確認を経てlatest追従を明示的に復旧します。これは旧方式へ戻す際だけの手動操作です。通常の新ワークフローとリビジョン切り戻しは、引き続き検証済みリビジョン名を指定します。

1. 両トリガーを無効のままにし、手動実行・main更新も止め、実行中ビルド・Cloud Run操作がないことを再確認します。ロックが残っている場合は残留ロックの復旧手順で状態を確定させます。バックアップや配置履歴から復旧元のリビジョン `APPROVED_REVISION` を選び、所属サービス・Ready条件・解決済みimageDigestを照合します。現在のlatestという理由だけで選びません。既存テンプレートの実行アカウント・シークレット参照・公開範囲もバックアップと一致することを確認し、不明・不一致なら中断します。シークレット値は取得しません。

```sh
gcloud run revisions describe APPROVED_REVISION --project=okinawago-dictionary --region=asia-southeast1 --format='yaml(metadata.name,metadata.labels,spec.containers.image,status.conditions,status.imageDigest)'
gcloud run services describe okinawago-dictionary-app --project=okinawago-dictionary --region=asia-southeast1 --format='yaml(spec.traffic,status.latestCreatedRevisionName,status.latestReadyRevisionName,status.traffic)'
```

2. 確認したイメージのdigestを `APPROVED_DIGEST` に指定し、復旧用リビジョンを送客なしで作ります。これにより、未検証の既存latestを選ばずに復旧対象を最新として配置できます。`UNIQUE_SUFFIX` は29文字以下の小文字英数字の固有値に置き換え、リビジョン名全体を63文字以下にします。タグは接尾辞と別に `RECOVERY_TAG`（例: `rc-0123456789abcdef`）を決め、先頭を小文字英字、末尾を小文字英数字、途中を小文字英数字・ハイフンにします。タグにも **`len(サービス名) + len(タグ) <= 46`** が必要で、24文字の `okinawago-dictionary-app` では **タグは22文字以下** です。選んだタグが既に存在しないことを直前のtraffic出力で確認し、復旧記録にもタグとリビジョン名の対応を残します。可変のイメージタグは使いません。

```sh
gcloud run services update okinawago-dictionary-app --project=okinawago-dictionary --region=asia-southeast1 --image=asia.gcr.io/okinawago-dictionary/okinawago-dictionary-app/okinawago-dictionary-app@sha256:APPROVED_DIGEST --revision-suffix=recovery-UNIQUE_SUFFIX --tag=RECOVERY_TAG --no-traffic
gcloud run revisions describe okinawago-dictionary-app-recovery-UNIQUE_SUFFIX --project=okinawago-dictionary --region=asia-southeast1 --format='yaml(metadata.name,metadata.labels,spec.containers.image,status.conditions,status.imageDigest)'
gcloud run services describe okinawago-dictionary-app --project=okinawago-dictionary --region=asia-southeast1 --format='yaml(metadata.generation,status.observedGeneration,status.conditions,status.latestCreatedRevisionName,status.latestReadyRevisionName,status.traffic)'
```

3. 作成したリビジョン名・所属サービス・Ready=True・imageDigestが承認したイメージと一致すること、本番trafficが維持されていること、タグ `RECOVERY_TAG` がそのリビジョンを指すことを確認します。そのタグに対応する `status.traffic[].url` を `RECOVERY_TAG_URL` に指定して、3辞書の検索・詳細本文、CSRF・CookieのHTTP確認を行います。失敗時は送客を変更せず中断します。

```sh
python3 scripts/smoke_http.py https://RECOVERY_TAG_URL.run.app --startup-timeout 90
```

4. 検証したリビジョンを名前で明示して100%へ切り替え、本番trafficと独自ドメインのHTTP動作を確認します。この段階で失敗した場合は、記録した旧リビジョンへの切り戻しを行い、latest追従の復旧へ進みません。

```sh
gcloud run services update-traffic okinawago-dictionary-app --project=okinawago-dictionary --region=asia-southeast1 --to-revisions=okinawago-dictionary-app-recovery-UNIQUE_SUFFIX=100
gcloud run services describe okinawago-dictionary-app --project=okinawago-dictionary --region=asia-southeast1 --format='yaml(spec.traffic,status.latestCreatedRevisionName,status.latestReadyRevisionName,status.traffic)'
python3 scripts/smoke_http.py https://okinawago.app --startup-timeout 90
```

5. 他の配置を止めた状態を維持し、直前のサービス出力で `latestCreatedRevisionName` と `latestReadyRevisionName` の**両方**がHTTP検証済みの `okinawago-dictionary-app-recovery-UNIQUE_SUFFIX` と一致し、本番も同リビジョンへ100%であることを再確認します。どれかが異なる、更新中、または確認後に別操作が入った場合は中断し、対象の検証からやり直します。これらを満たした場合だけ、次のコマンドで[今後のlatestにも追従する割当](https://docs.cloud.google.com/sdk/gcloud/reference/run/services/update-traffic)を復旧します。

```sh
gcloud run services update-traffic okinawago-dictionary-app --project=okinawago-dictionary --region=asia-southeast1 --to-latest
gcloud run services describe okinawago-dictionary-app --project=okinawago-dictionary --region=asia-southeast1 --format='yaml(spec.traffic,status.latestCreatedRevisionName,status.latestReadyRevisionName,status.traffic)'
python3 scripts/smoke_http.py https://okinawago.app --startup-timeout 90
```

6. `spec.traffic` が `latestRevision: true`・100%であり、解決済みの `status.traffic` が同じ検証済み復旧リビジョンへ100%であることとHTTP成功を確認します。自分の復旧タグが同リビジョンを指していることを確認して `--remove-tags=RECOVERY_TAG` で片付け、trafficを再確認します。旧Inlineの復元内容と送客動作の復旧結果を記録した後、本番トリガーだけを再有効化します。再有効化後の最初の旧方式ビルドでも、配置したイメージ・Ready・実際の送客先・本番HTTPを確認してください。

旧方式では以後の新版へ自動送客され、新ワークフローの切り替え前HTTP検証は適用されません。ビルド専用トリガーの再有効化は、二重build/pushの必要性を確認してから行います。旧Inlineの直接traffic変更にはこのワークフローのロック・順序保護がないため、新旧の反映を並行稼働させないでください。状態バケットやwatermarkは消さず、再移行時も履歴を維持します。

## 通常運用・本番確認

main更新後に本番トリガーが一度だけ走ること、各段階の結果、記録の `previous_traffic` と `revision` を確認します。タグ操作は[Cloud Runのtrafficコマンド](https://docs.cloud.google.com/sdk/gcloud/reference/run/services/update-traffic)の `--remove-tags=自分のタグ` だけを使い、既存タグ・他ビルドのタグをまとめて消しません。

```sh
gcloud builds describe BUILD_ID --project=okinawago-dictionary --region=global --format='yaml(id,status,createTime,serviceAccount)'
gcloud run services describe okinawago-dictionary-app --project=okinawago-dictionary --region=asia-southeast1 --format='yaml(status.traffic)'
gcloud storage ls gs://STATE_BUCKET/release/records/BUILD_ID/
gcloud storage cat gs://STATE_BUCKET/release/records/BUILD_ID/ATTEMPT.json
python3 scripts/smoke_http.py https://okinawago.app --startup-timeout 90
```

公開ドメインのHTTP確認に加え、[開発ガイドの手動確認](development.md#自動確認と手動確認の範囲)も行います。自動化内のHTTP確認は新リビジョン専用URLで切り替え前に実行されます。

ロック待ち300秒、gcloudのRunコマンド300秒、GCS HTTP要求30秒、専用URL起動待ち90秒、HTTP確認プロセス180秒などの上限があります。Cloud Build全体は2400秒、releaseステップは1500秒です。外側の期限・キャンセル・強制終了によって後片付けが完了しない場合は、次の復旧手順を使います。

## 失敗・後片付け

配置・HTTP確認・照合の失敗は非ゼロ終了し、切り替えを呼びません。既知の安全な状態では失敗後も自分のタグを削除し、ロックを解放します。後片付けの失敗をログ・記録に残し、元の失敗を上書きしません。traffic更新自体の通信障害では実際には切り替わった可能性があり、自動切り戻しは行いません。

gcloudの変更要求でエラー・タイムアウト・割り込みが起きた場合は結果を断定せず、ロックとタグを残して復旧を要求します。所有権を失った場合やタグの対応先が別リビジョンだった場合も、それらを削除・解放しません。タグ削除や最終記録に失敗した場合もロックを残します。

Cloud Runコマンドの非ゼロ終了は、操作名（例: `gcloud run services update`）、終了コード、原因のstderrをログ・失敗記録に残します。タイムアウト時は終了コードを不明とし、取得できたstderrを記録します。stderrは認証情報を伏せ、JSON/YAMLの設定出力を省略し、最大4000文字に制限します。stdoutのサービス定義や認証コマンドの出力はエラーへ含めません。診断情報を追加しても、結果不明時にロックを維持する判断は変わりません。

現在のリビジョン最小インスタンス数は1です。検証用タグが残ると、0%のリビジョンでも追加稼働・課金につながる場合があります。通常終了ではタグを削除し、復旧時も所有者と操作状態を照合して早めに片付けます。リビジョン自体の自動削除や最小インスタンス設定の変更は行いません。

## 切り戻し

本番トリガーを一時停止し、実行中・待機中ビルドとCloud Run更新がすべて終わっていることを確認します。ロックが残っている場合は先に次節の復旧判断を行います。記録の `previous_traffic` から旧リビジョンを取り出し、存在・Ready・イメージ・設定を確認して名前を明示指定します。通常の100%割当なら次を使います。

```sh
gcloud run revisions describe OLD_REVISION --project=okinawago-dictionary --region=asia-southeast1 --format='yaml(metadata.name,status.conditions,status.imageDigest)'
gcloud run services update-traffic okinawago-dictionary-app --project=okinawago-dictionary --region=asia-southeast1 --to-revisions=OLD_REVISION=100
gcloud run services describe okinawago-dictionary-app --project=okinawago-dictionary --region=asia-southeast1 --format='yaml(status.traffic)'
python3 scripts/smoke_http.py https://okinawago.app --startup-timeout 90
```

元が複数リビジョンの場合は、記録通り `--to-revisions=OLD_A=割合,OLD_B=割合` を明示し合計100%にします。`--to-latest` は使いません。切り戻した日時・対象・理由・確認結果を運用記録へ残し、watermarkを巻き戻さないでください。原因を修正した新しいmainビルドで再開します。

リビジョン切り戻しだけでSecret Manager、IAM、独自ドメイン、外部サービスなどの変更が復旧するとは限りません。SECRET_KEYを変えるとFlaskの既存セッションが無効になります。外部設定の復旧は別途担当者が判断し、本手順では値の取得・変更を行いません。

## 残留ロックの復旧

時間経過だけでロックを奪いません。次の順番で手動復旧します。

1. 両トリガーを停止し、これ以上ビルドを開始しない。`release/state.json` と対象記録を読み、ownerのビルドID・試行ID、世代番号を控える。
2. ownerのビルドを **そのビルドのリージョン** でdescribeし、`SUCCESS` / `FAILURE` / `INTERNAL_ERROR` / `TIMEOUT` / `CANCELLED` / `EXPIRED` の終端状態を確認する。`PENDING` / `QUEUED` / `WORKING` なら解放しない。不明・権限不足・見つからない場合も解放しない。
3. Cloud Run Consoleの操作履歴・リビジョンとサービス状態で配置・traffic変更が実行中でないことを確認する。Cloud Buildが終端でもRunの操作が継続している場合は待つ。記録のrevision・digest・タグと現状のtrafficを照合し、反映結果不明を解消する。必要なら前節の切り戻しを実施する。
4. 終了済みownerのタグが記録のrevisionを指している時だけ、そのタグ名を `--remove-tags=TAG` で削除する。他のrevisionを指す、対応不明、既存・他ビルドのタグなら操作せず調査する。残留タグの追加稼働に注意する。
5. **同じowner・世代であることを再確認**し、watermark / last_promotedなどをすべて保持してownerだけ空にしたJSONを世代条件付きで保存する。412競合時は中断し、再確認する。stateを削除して作り直さない。

参照・復旧用CLI例:

```sh
gcloud storage objects describe gs://STATE_BUCKET/release/state.json --format='value(generation)'
gcloud storage cat gs://STATE_BUCKET/release/state.json
gcloud builds describe OWNER_BUILD_ID --project=okinawago-dictionary --region=OWNER_BUILD_REGION --format='yaml(id,status,finishTime)'
gcloud run services describe okinawago-dictionary-app --project=okinawago-dictionary --region=asia-southeast1 --format='yaml(metadata.generation,status.observedGeneration,status.conditions,status.traffic)'
gcloud run services update-traffic okinawago-dictionary-app --project=okinawago-dictionary --region=asia-southeast1 --remove-tags=OWNER_TAG
```

上記の安全確認をすべて終えてから、読み取る世代番号を固定してファイルを作ります。次のPythonのowner文字列も記録の実値へ置き換えてください。ここでの世代番号は最初の照合から同じ値を使用します。

```sh
gcloud storage cp 'gs://STATE_BUCKET/release/state.json#GENERATION' /tmp/okinawago-state-before.json
python3 -c 'import json; from pathlib import Path; p=Path("/tmp/okinawago-state-before.json"); s=json.loads(p.read_text()); assert s["owner"] == {"build_id": "OWNER_BUILD_ID", "attempt": "OWNER_ATTEMPT"}; s["owner"]=None; Path("/tmp/okinawago-state-recovered.json").write_text(json.dumps(s)+"\n")'
gcloud storage cp /tmp/okinawago-state-recovered.json gs://STATE_BUCKET/release/state.json --if-generation-match=GENERATION
```

解放結果・traffic・タグ・watermarkの維持を読み直し、復旧記録を保存します。修正後は `_PROMOTE=false` で再確認し、本番トリガーのみ通常運用へ戻します。手動復旧でownerや世代の確認を省略すると、進行中の正しい実行を破壊するため、確認できない場合は停止を維持します。
