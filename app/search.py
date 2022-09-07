import json
from typing import List

with open("app/static/okinawa_01.json", 'r') as raw_file:
    oki_dict = json.load(raw_file)
key_dict = {}
content_dict = {}
for i, entry in enumerate(oki_dict):
    for index in entry["index"]:
        key_dict[index] = i
    content_dict[i] = entry


def search(word: str) -> List:
    key = key_dict.get(word)
    if not key:
        return []
    return [content_dict[key]]
