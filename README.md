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
