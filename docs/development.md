# 開発ガイド

## 環境準備と起動

Python 3.10とPoetryを用意し、リポジトリのルートで実行します。

```sh
poetry install
env SECRET_KEY=development-only-secret poetry run flask --app app.main run --debug
poetry run python -m unittest discover -s tests -v
```

`SECRET_KEY` は空でない値が必須で、未設定・空文字の場合は明示的なエラーで起動を中止します。ローカルでは開発専用の値を使い、本番の値を取得したりリポジトリへ保存したりしないでください。テストコードは固定のテスト専用シークレットを設定します。デバッグモードは `--debug` でローカル時のみ明示的に有効化します。本番起動にはDockerfileのGunicornを使います。シークレットの参照・運用は[デプロイガイド](deployment.md)を参照してください。

## ローカル・CI共通の自動チェック

必要なツールはGNU Make、Python 3.10以上（確認スクリプト自体は標準ライブラリのみ）、起動済みのDocker Engineです。初回ビルドにはベースイメージと依存パッケージを取得するネットワーク接続が必要です。PoetryやGCPの認証、本番シークレットは不要です。

```sh
make check
git diff --check
```

Dockerfileからアプリイメージを一度ビルドし、その中でunittestをすべて実行します。アプリ・検索処理の既存17テストと、GCPへアクセスしないデプロイ制御テストが含まれます。続けて同じイメージを通常のCMD（Gunicorn）で起動し、HTTP経由で次を確認します。

- トップページ、CSRFトークン、Cookieを保持した検索送信
- 沖日辞典: 「あー」→「アー」、詳細本文「物事に深く感じた時発する声」
- 日沖辞典: 「ああ」、詳細本文「アキヨ」
- うちなーぐち活用辞典: 「あーいん」→「アーイン」、詳細本文「〈合う〉」

CSRF対策は有効なままで、HTTP 200だけでは成功になりません。別オリジンへのリダイレクトも拒否します。

チェック用サーバーには固定のテスト専用 `SECRET_KEY` を渡し、ホストの本番の値を引き継ぎません。HTTPクライアント用コンテナをサーバーと同じネットワーク名前空間で実行するため、ポート公開は不要です。呼び出し元がCloud Buildのステップコンテナでも、Dockerデーモン側のサーバーへ接続できます。

成功・失敗・通常の割り込み時には作成したコンテナとチェック用イメージを削除します（ビルドキャッシュは残ります）。強制終了やDocker自体の停止時は手動の片付けが必要な場合があります。失敗は非ゼロ終了で通知し、サーバーの失敗時はコンテナログも表示します。コンテナ・イメージ削除の問題はログに残ります。

既にビルドしたイメージを確認する場合は次のコマンドを使います。このモードはイメージをビルド・削除しません。Cloud Buildもこの処理を共有します。

```sh
python3 scripts/check.py --image YOUR_EXISTING_IMAGE
```

HTTP確認は単独でも再利用できます。検証対象へのアクセスを許可したURLを指定してください。

```sh
python3 scripts/smoke_http.py http://127.0.0.1:8080
python3 scripts/smoke_http.py https://YOUR_TAG_URL.run.app --startup-timeout 90
```

起動待ちは標準60秒、各HTTP接続・読み取りは最大5秒です。Docker確認の各コマンドにも上限があります。このスクリプトは対象サーバーの設定を変更しません。

## 自動確認と手動確認の範囲

自動確認は基本機能の疎通とunittestの範囲が対象です。PC・スマホでの見た目、文字やレイアウトの崩れ、タップ・キーボード操作、使いやすさ、すべての辞書項目の正しさは別途手動で確認してください。

## GitHubの必須チェック設定

GitHub Actionsの `CI` ワークフローは、main向けpull requestとmainへのpushで `make check` を実行します。ジョブ名は **`Docker check`** です。GCPや本番シークレットを使用せず、GitHub権限は `contents: read` のみです。同じPRの古い実行は更新時にキャンセルされます。

リポジトリ管理者は、一度実行された後にGitHubの Settings → Branches → mainのブランチ保護ルールで「Require status checks to pass before merging」を有効にし、**`Docker check`** を選んで保存してください。Rulesetsの場合は Settings → Rules → Rulesetsでmainを対象にし、「Require status checks to pass」に同じチェックを追加します。リポジトリのファイル追加だけでは有効になりません。

Cloud Buildでも配置前に同じDocker確認を実行します。GitHub Actionsの実行完了を待つ構成ではないため、mainの保護とCloud Build自身の確認を両方維持します。
