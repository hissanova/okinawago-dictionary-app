import json
from typing import Callable, Dict, List, Tuple

with open("app/static/okinawa_01.json", 'r') as raw_file:
    raw_oki_dict = json.load(raw_file)

with open("app/static/okinawa_02.json", 'r') as raw_file:
    raw_yamato_dict = json.load(raw_file)


class Dictionary():
    def __init__(self, word_dict):
        key_dict: Dict[str, List[int]] = {}
        content_dict = {}
        for i, entry in enumerate(word_dict):
            for index in entry["index"]:
                key_list = key_dict.setdefault(index, [])
                key_dict[index] = key_list + [i]
            content_dict[i] = entry
        self._key_dict = key_dict
        self._content_dict = content_dict
        # print(self._key_dict)

    @property
    def index_words(self):
        return self._key_dict.keys()

    def get_keys(self, index_word: str) -> List[int]:
        return self._key_dict[index_word]

    def get_content(self, key: int):
        return self._content_dict[key]


oki_dict = Dictionary(raw_oki_dict)
yamato_dict = Dictionary(raw_yamato_dict)


def _get_dict(dict_type: str) -> Dictionary:
    if dict_type == 'oki2yamato':
        return oki_dict
    elif dict_type == 'yamato2oki':
        return yamato_dict
    else:
        raise NotImplementedError


def _get_filter(word: str, search_type: str) -> Callable[[str], bool]:
    if search_type == "startswith":
        def filter_(key: str) -> bool:
            return key.startswith(word)
    elif search_type == "endswith":
        def filter_(key: str) -> bool:
            return key.endswith(word)
    return filter_


def _sort(word_list: List[List[str]]) -> List[List[str]]:
    return sorted(word_list)


def search(word: str,
           search_type: str,
           dict_type: str) -> List[List[str]]:
    # print(f"In search(): dict_type={dict_type}")
    results_dict: Dict[Tuple[int, ...], List[str]] = {}
    index_filter = _get_filter(word, search_type)
    dictionary = _get_dict(dict_type)
    # print(f"dictionary={dictionary}")
    for index_word in dictionary.index_words:
        if index_filter(index_word):
            id_keys = tuple(dictionary.get_keys(index_word))
            index_words = results_dict.setdefault(id_keys, [])
            results_dict[id_keys] = index_words + [index_word]
    return _sort(list(results_dict.values()))


def get_contents(key_word: str, dict_type: str):
    # print(f"In get_contents(): dict_type={dict_type}")
    dictionary = _get_dict(dict_type)
    keys = dictionary.get_keys(key_word)
    if not keys:
        return []
    return [dictionary.get_content(key) for key in keys]
