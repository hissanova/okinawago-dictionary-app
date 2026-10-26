import importlib
import os
import subprocess
import sys
import unittest
from html.parser import HTMLParser


os.environ["SECRET_KEY"] = "deterministic-test-secret"
main = importlib.import_module("app.main")


class FormParser(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.inputs = {}
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "input" and "name" in attrs:
            self.inputs[attrs["name"]] = attrs.get("value", "")


class AppTest(unittest.TestCase):
    def setUp(self):
        original_config = main.app.config.copy()
        self.addCleanup(lambda: (main.app.config.clear(), main.app.config.update(original_config)))
        main.app.config.update(TESTING=True, WTF_CSRF_ENABLED=True)
        self.client = main.app.test_client()

    def token(self, client=None):
        client = client or self.client
        response = client.get("/")
        self.assertEqual(200, response.status_code)
        token = FormParser(response.get_data(as_text=True)).inputs["csrf_token"]
        self.assertTrue(token)
        return token

    def post_form(self, data, **kwargs):
        return self.client.post("/", data={"csrf_token": self.token(), **data}, **kwargs)

    def test_app_uses_test_secret_and_debug_is_disabled(self):
        self.assertEqual("deterministic-test-secret", main.app.config["SECRET_KEY"])
        self.assertFalse(main.app.debug)

    def test_missing_secret_prevents_startup(self):
        environment = os.environ.copy()
        environment.pop("SECRET_KEY", None)

        result = subprocess.run(
            [sys.executable, "-c", "import app.main"],
            cwd=os.path.dirname(os.path.dirname(__file__)),
            env=environment,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("SECRET_KEY environment variable must be set", result.stderr)

    def test_empty_query_shows_validation_error(self):
        response = self.post_form(data={"word": ""})

        self.assertEqual(200, response.status_code)
        self.assertIn("検索語の入力", response.get_data(as_text=True))

    def test_normal_search_still_returns_highlighted_results(self):
        response = self.post_form(
            data={
                "word": "あ",
                "search_type": "startswith",
                "dict_type": "oki2yamato",
            },
            follow_redirects=True,
        )

        self.assertEqual(200, response.status_code)
        self.assertIn("<b>ア</b>", response.get_data(as_text=True))

    def test_regex_metacharacter_searches_do_not_return_server_errors(self):
        for query in ["[", "(", "*", "?", "\\", ".*"]:
            with self.subTest(query=query):
                response = self.post_form(
                    data={
                        "word": query,
                        "search_type": "contains",
                        "dict_type": "oki2yamato",
                    },
                    follow_redirects=True,
                )
                self.assertEqual(200, response.status_code)

    def test_over_limit_query_shows_validation_error(self):
        response = self.post_form(
            data={"word": "あ" * (main.MAX_SEARCH_QUERY_LENGTH + 1)},
        )

        self.assertEqual(200, response.status_code)
        self.assertIn("Field cannot be longer than", response.get_data(as_text=True))

    def test_get_contains_csrf_token(self):
        self.token()

    def test_valid_submission_redirects_and_renders_results(self):
        response = self.post_form(data={
            "word": "あ", "search_type": "startswith", "dict_type": "oki2yamato",
        })
        self.assertEqual(302, response.status_code)
        self.assertIn("/search-results/", response.location)
        with self.client.session_transaction() as session:
            self.assertEqual("あ", session["word"])
            self.assertEqual("startswith", session["search_type"])
            self.assertEqual(["oki2yamato"], session["dict_type"])
        results = self.client.get(response.location)
        self.assertEqual(200, results.status_code)
        self.assertIn("<b>ア</b>", results.get_data(as_text=True))

    def assert_rejected(self, data, error):
        previous = {"word": "以前", "search_type": "endswith", "dict_type": ["yamato2oki"]}
        with self.client.session_transaction() as session:
            session.update(previous)
        response = self.client.post("/", data=data)
        self.assertEqual(200, response.status_code)
        self.assertNotIn("Location", response.headers)
        html = response.get_data(as_text=True)
        self.assertIn(error, html)
        self.assertEqual(data["word"], FormParser(html).inputs["word"])
        with self.client.session_transaction() as session:
            self.assertEqual(previous, {key: session[key] for key in previous})
        return html

    def test_invalid_csrf_tokens(self):
        for kind in ["missing", "tampered", "other_session"]:
            with self.subTest(kind=kind):
                token = self.token()
                data = {"word": '<script>alert("入力")</script>',
                        "search_type": "contains", "dict_type": "oki2yamato"}
                if kind == "tampered":
                    data["csrf_token"] = token + "tampered"
                elif kind == "other_session":
                    data["csrf_token"] = self.token(main.app.test_client())
                html = self.assert_rejected(data, "ページを再読み込みして、もう一度検索してください")
                self.assertNotIn(data["word"], html)
                self.assertIn("&lt;script&gt;", html)

    def test_invalid_choices_with_valid_csrf(self):
        for field, value, label in [
            ("search_type", "invalid", "検索方法："),
            ("dict_type", "invalid", "辞書選択："),
            ("dict_type", ["oki2yamato", "invalid"], "辞書選択："),
        ]:
            with self.subTest(field=field, value=value):
                data = {"csrf_token": self.token(), "word": "入力語",
                        "search_type": "contains", "dict_type": "oki2yamato"}
                data[field] = value
                html = self.assert_rejected(data, label)
                self.assertNotIn("ページを再読み込みして", html)

    def test_defaults_and_no_dictionary_selection_are_preserved(self):
        response = self.post_form(data={"word": "あ"})
        self.assertEqual(302, response.status_code)
        with self.client.session_transaction() as session:
            self.assertEqual("contains", session["search_type"])
            self.assertEqual([], session["dict_type"])
        self.assertEqual(200, self.client.get(response.location).status_code)

    def test_about_page_contains_dataset_attribution(self):
        page = self.client.get("/about").get_data(as_text=True)

        self.assertIn("沖縄語辞典 データ集", page)
        self.assertIn("https://mmsrv.ninjal.ac.jp/okinawago/", page)
        self.assertIn("https://creativecommons.org/licenses/by/4.0/deed.ja", page)
        self.assertIn("検索・表示用に変換・加工", page)


if __name__ == "__main__":
    unittest.main()
