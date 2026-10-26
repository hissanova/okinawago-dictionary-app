# 沖縄語辞典 Webアプリ

国立国語研究所の沖縄語辞典のデータを使った辞書検索Webアプリです。
https://github.com/hissanova/okinawago_dictionary のデータを用いています。

## ローカル開発

Python 3.10 と Poetry を用意し、依存関係をインストールします。

```sh
poetry install
export SECRET_KEY='development-only-secret'
poetry run flask --app app.main run --debug
```

`SECRET_KEY` は必須です。ローカル開発では開発専用の値を使い、本番用の値をリポジトリにコミットしないでください。デバッグモードは上記の `--debug` でローカル時のみ明示的に有効化します。

テストは次のように実行します。テストコードは固定のテスト専用シークレットを設定します。

```sh
poetry run python -m unittest discover -s tests -v
```

## 本番環境

本番起動には空でない `SECRET_KEY` 環境変数が必要です。未設定の場合、アプリケーションは明示的なエラーで起動を中止します。Cloud Run へデプロイする前に、Secret Manager などから `SECRET_KEY` をサービスの環境変数として設定してください。値を変更すると、既存の Flask セッションは無効になります。

Cloud Run では Dockerfile の Gunicorn コマンドがアプリケーションを起動します。Flask の開発サーバーやデバッグモードは本番起動で使用しません。

## ローカル・CI共通の自動チェック

必要なツールは GNU Make、Python 3.10以上（標準ライブラリのみ）、起動済みのDocker Engineです。初回ビルドにはベースイメージと依存パッケージを取得するネットワーク接続が必要です。PoetryやGCPの認証、本番シークレットは不要です。

```sh
make check
```

Dockerfileからイメージを一度ビルドし、その中で既存のunittestをすべて実行します。続けて同じイメージを通常のCMD（Gunicorn）で起動し、HTTP経由でトップページ・CSRFトークン・Cookie付きの検索送信・沖日辞典（「あー」→「アー」）、日沖辞典（「ああ」）、うちなーぐち活用辞典（「あーいん」→「〈合う〉」）の検索結果および詳細本文を確認します。CSRF対策は有効なままで、HTTP 200だけでは成功になりません。

チェック用コンテナには固定のテスト専用 `SECRET_KEY` を明示的に渡します。ホストの本番用の値は引き継ぎません。ローカルの空きポートをDockerに割り当てさせ、成功・失敗・通常の割り込み時には作成したコンテナとチェック用イメージを削除します（Dockerのビルドキャッシュは残ります）。強制終了やDocker自体の停止時には手動の片付けが必要な場合があります。失敗はコマンドの非ゼロ終了で通知し、サーバーの失敗時にはコンテナログも表示します。

HTTP確認は単独でも再利用できます。検証対象へのアクセスを許可したURLを指定してください。

```sh
python3 scripts/smoke_http.py http://127.0.0.1:8080
# 次のPRで用意するCloud Run検証用URLにも同じ形式で実行できます。
python3 scripts/smoke_http.py https://example.run.app --startup-timeout 60
```

起動待ちは標準で60秒、各HTTP接続・読み取りのタイムアウトは最大5秒です。このスクリプトは対象サーバーの設定を変更しません。

自動確認は基本機能の疎通と既存unittestの範囲を対象にします。PC・スマホでの見た目、文字やレイアウトの崩れ、タップ・キーボード操作、使いやすさ、すべての辞書項目の正しさは別途手動で確認してください。

### GitHubの必須チェック設定

GitHub Actionsの `CI` ワークフローは、main向けのpull requestとmainへのpushで `make check` を実行します。安定したジョブ名は **`Docker check`** です。GCPや本番シークレットを使用せず、GitHub権限は `contents: read` のみです。同じPRの古い実行は更新時にキャンセルされます。

リポジトリ管理者は、このワークフローが一度実行された後に、GitHubの Settings → Branches → mainのブランチ保護ルールで「Require status checks to pass before merging」を有効にし、**`Docker check`** を選んで保存してください。Rulesetsを使う場合は、Settings → Rules → Rulesetsでmainを対象にし、「Require status checks to pass」に同じチェックを追加します。この設定はリポジトリ内のファイル追加だけでは有効になりません。

このPRはCIのみを扱います。Cloud Buildトリガー、Cloud Run、IAM、Secret Managerおよび本番用cloudbuild.yamlは次のPRで扱います。
