from typing import Callable, Dict, List, Tuple

from app.okinawago_dictionary.scripts.dictionary import Dictionary, oki_dict, yamato_dict


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
    results_dict: Dict[Tuple[int, ...], List[str]] = {}
    dictionary = _get_dict(dict_type)
    index_filter = _get_filter(dictionary.normalise_kana(word), search_type)
    for index_word in dictionary.index_words:
        if index_filter(index_word):
            id_keys = tuple(dictionary.get_keys(index_word))
            index_words = results_dict.setdefault(id_keys, [])
            results_dict[id_keys] = index_words + [index_word]
    return _sort(list(results_dict.values()))


def get_contents(key_word: str, dict_type: str):
    dictionary = _get_dict(dict_type)
    keys = dictionary.get_keys(key_word)
    if not keys:
        return []
    return [dictionary.get_content(key) for key in keys]
