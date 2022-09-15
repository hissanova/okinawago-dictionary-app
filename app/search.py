import json
from typing import Dict, List

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
