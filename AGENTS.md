# エージェント向け作業ガイド

## 構成

- `app/main.py`: Flaskアプリ、検索フォームの検証、検索結果・詳細表示のルート。
- `app/search.py`: 辞書検索、検索語の正規化、結果の強調表示。
- `app/templates/`・`app/static/`: 画面テンプレートと静的ファイル。
- `extra_wheels/`: 沖日辞典・日沖辞典・うちなーぐち活用辞典のデータを含むPythonパッケージ。
- `tests/`: unittestによるアプリ・検索処理のテスト。
- `scripts/check.py`・`scripts/smoke_http.py`: Dockerでの共通チェックとURL指定のHTTP確認。
- `cloudbuild.release.yaml`・`scripts/release.py`: 同一イメージの検証・保存、排他制御付きCloud Run配置と切り替え。
- `scripts/build_release.sh`・`scripts/publish_image.py`: 一度だけのビルドと保存先digestの照合。
- `docs/development.md`・`docs/deployment.md`: 開発・確認とデプロイ移行・運用・復旧の詳細。
- `Dockerfile`: 本番と共通のイメージ定義とGunicorn起動コマンド。
- `.github/workflows/check.yml`: main向けPRとmainへのpushで `make check` を実行するCI。

## 準備・起動・確認

開発にはPython 3.10とPoetryを使う。

```sh
poetry install
env SECRET_KEY=development-only-secret poetry run flask --app app.main run --debug
poetry run python -m unittest discover -s tests -v
```

変更後の標準確認コマンドは次のとおり。GNU Make、Python 3.10以上、起動済みDocker Engineが必要。

```sh
make check
git diff --check
```

`make check` はDockerfileを一度ビルドし、同じイメージで全unittestと通常のCMD（Gunicorn）によるHTTP確認を行う。HTTP確認だけの場合は `python3 scripts/smoke_http.py <ベースURL>` を使う。準備、確認範囲、手動確認、GitHubの必須チェック設定は [開発ガイド](docs/development.md)、Cloud Runの配置・移行・切り戻し・ロック復旧は [デプロイガイド](docs/deployment.md) を参照する。

## 作業ルール

- ユーザーの既存差分を維持し、無関係な変更を混ぜない。
- 機能追加・不具合修正には、変更した振る舞いを検証するテストを追加・更新する。既存テストの削除や検証の弱体化で失敗を回避しない。
- 検索、3種類の辞書の選択、CSRF、入力エラー時の表示と入力保持を維持する。
- `SECRET_KEY` は開発・テスト専用の値を使い、本番の値をコードやログへ出さない。
- レビュー用の差分・ログは `/tmp` などリポジトリ外に保存し、コミット対象に含めない。
- 検証結果を報告し、未実施の確認は実施済みと区別して理由を記載する。
- コミット・push・マージ・本番設定変更・デプロイは、ユーザーから指示された範囲で行う。
- 本番用のルート `cloudbuild.yaml` を追加しない。デプロイは既存サービスとシークレット参照を維持し、検証済みリビジョンを明示する。ロック・順序情報の自動破棄や、他実行のタグ削除を行わない。
