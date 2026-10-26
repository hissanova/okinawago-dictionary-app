import unittest
from unittest.mock import patch

from app import search as search_module


class FakeDictionary:
    index_words = [
        "かな",
        "おかな",
        "[かな",
        "(かな",
        "*かな",
        "?かな",
        "\\かな",
        ".*かな",
    ]

    @staticmethod
    def normalise_kana(word):
        return word

    def get_keys(self, word):
        return [self.index_words.index(word)]


class SearchTest(unittest.TestCase):
    def setUp(self):
        self.dictionary = FakeDictionary()
        self.patches = [
            patch.object(search_module, "oki_dict", self.dictionary),
            patch.object(search_module, "_get_dict", return_value=self.dictionary),
        ]
        for active_patch in self.patches:
            active_patch.start()

    def tearDown(self):
        for active_patch in reversed(self.patches):
            active_patch.stop()

    def test_normal_japanese_query_and_existing_highlighting(self):
        results = search_module.search("かな", "contains", ["oki2yamato"])

        self.assertEqual(8, len(results))
        self.assertEqual("<b>かな</b>", results[0].matched_words_for_display[0])

    def test_regex_metacharacters_are_treated_as_literal_text(self):
        for query in ["[", "(", "*", "?", "\\", ".*"]:
            with self.subTest(query=query):
                results = search_module.search(query, "contains", ["oki2yamato"])
                self.assertGreaterEqual(len(results), 1)
                for result in results:
                    self.assertIn(query, result.matched_words[0])
                    self.assertIn(f"<b>{query}</b>", result.matched_words_for_display[0])

    def test_empty_query_returns_no_results(self):
        self.assertEqual([], search_module.search("", "contains", ["oki2yamato"]))

    def test_non_string_query_returns_no_results(self):
        self.assertEqual([], search_module.search(None, "contains", ["oki2yamato"]))

    def test_over_limit_query_returns_no_results(self):
        query = "あ" * (search_module.MAX_SEARCH_QUERY_LENGTH + 1)
        self.assertEqual([], search_module.search(query, "contains", ["oki2yamato"]))


if __name__ == "__main__":
    unittest.main()
