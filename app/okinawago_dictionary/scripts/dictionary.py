from abc import abstractmethod
import json
import os
from typing import Dict, List

from wanakana import to_hiragana, to_katakana


callers_dir = os.path.abspath(os.path.curdir)

oki2yamato_dict_dir = f"{callers_dir}/app/okinawago_dictionary/resources/base_lists/okinawa_01.json"
yamata2oki_dict_dir = f"{callers_dir}/app/okinawago_dictionary/resources/base_lists/okinawa_02.json"

with open(oki2yamato_dict_dir, 'r') as raw_file:
    raw_oki_dict = json.load(raw_file)

with open(yamata2oki_dict_dir, 'r') as raw_file:
    raw_yamato_dict = json.load(raw_file)


class Dictionary:
    def __init__(self, raw_word_dict):
        index_to_key_dict: Dict[str, List[int]] = {}
        content_dict = {}
        for i, entry in enumerate(raw_word_dict):
            for index in entry["index"]:
                key_list = index_to_key_dict.setdefault(index, [])
                index_to_key_dict[index] = key_list + [i]
            content_dict[i] = entry
        self._index_to_key_dict = index_to_key_dict
        self._content_dict = content_dict

    @property
    def index_words(self):
        return self._index_to_key_dict.keys()

    def get_keys(self, index_word: str) -> List[int]:
        return self._index_to_key_dict[index_word]

    def get_content(self, key: int):
        return self._content_dict[key]

    @abstractmethod
    def normalise_kana(self, kana_str: str) -> str:
        raise NotImplementedError


class OkinawagoDictionary(Dictionary):
    """Documentation for OkinawagoDictionary

    """
    def __init__(self, raw_oki_dict):
        super(OkinawagoDictionary, self).__init__(raw_oki_dict)

    def normalise_kana(self, kana_str: str) -> str:
        return to_katakana(kana_str)


class YamatogoDictionary(Dictionary):
    """Documentation for YamatoDictionary

    """
    def __init__(self, raw_yamato_dict):
        super(YamatogoDictionary, self).__init__(raw_yamato_dict)

    def normalise_kana(self, kana_str: str) -> str:
        return to_hiragana(kana_str)


oki_dict = OkinawagoDictionary(raw_oki_dict)
yamato_dict = YamatogoDictionary(raw_yamato_dict)
