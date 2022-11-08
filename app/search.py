from typing import Callable, Dict, List, Tuple

from app.app.okinawago_dictionary.scripts.dictionary import Dictionary, oki_dict, yamato_dict


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


def search(query_word: str,
           search_type: str,
           dict_type: str) -> List[List[str]]:
    dictionary = _get_dict(dict_type)
    match_filter = _get_filter(dictionary.normalise_kana(query_word), search_type)
    matched_words: Dict[Tuple[int, ...], List[str]] = {}
    for candidate_word in dictionary.index_words:
        if match_filter(candidate_word):
            matched_ids = tuple(dictionary.get_keys(candidate_word))
            words_with_same_ids = matched_words.setdefault(matched_ids, [])
            matched_words[matched_ids] = words_with_same_ids + [candidate_word]
    return _sort(list(matched_words.values()))


def get_contents(key_word: str, dict_type: str):
    dictionary = _get_dict(dict_type)
    keys = dictionary.get_keys(key_word)
    if not keys:
        return []
    return [dictionary.get_content(key) for key in keys]
