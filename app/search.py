import json
from typing import Callable, Dict, List

with open("app/static/okinawa_01.json", 'r') as raw_file:
    oki_dict = json.load(raw_file)
key_dict: Dict[str, List[int]] = {}
content_dict = {}
for i, entry in enumerate(oki_dict):
    for index in entry["index"]:
        key_list = key_dict.setdefault(index, [])
        key_dict[index] = key_list + [i]
    content_dict[i] = entry


def search(word: str) -> List:
    keys = key_dict.get(word)
    if not keys:
        return []
    return [content_dict[key] for key in keys]


def get_filter(word: str, search_type: str) -> Callable[[str], bool]:
    if search_type == "startswith":
        def filter_(key: str) -> bool:
            return key.startswith(word)
    elif search_type == "endswith":
        def filter_(key: str) -> bool:
            return key.endswith(word)
    return filter_


def _search(word: str, search_type: str) -> List[str]:
    results = []
    key_filter = get_filter(word, search_type)
    for key in key_dict.keys():
        if key_filter(key):
            results.append(key)
    return results
