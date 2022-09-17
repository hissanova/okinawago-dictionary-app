import json
from typing import Callable, Dict, List, Tuple

with open("app/static/okinawa_01.json", 'r') as raw_file:
    oki_dict = json.load(raw_file)
key_dict: Dict[str, List[int]] = {}
content_dict = {}
for i, entry in enumerate(oki_dict):
    for index in entry["index"]:
        key_list = key_dict.setdefault(index, [])
        key_dict[index] = key_list + [i]
    content_dict[i] = entry


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


def search(word: str, search_type: str) -> List[List[str]]:
    results_dict: Dict[Tuple[int, ...], List[str]] = {}
    index_filter = _get_filter(word, search_type)
    for index_word in key_dict.keys():
        if index_filter(index_word):
            id_keys = tuple(key_dict[index_word])
            index_words = results_dict.setdefault(id_keys, [])
            results_dict[id_keys] = index_words + [index_word]
    return _sort(list(results_dict.values()))


def get_contents(key_word):
    keys = key_dict.get(key_word)
    if not keys:
        return []
    return [content_dict[key] for key in keys]
