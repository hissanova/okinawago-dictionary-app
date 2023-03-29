from typing import Callable, Dict, List, NamedTuple, Optional, Tuple
import re

from wanakana import to_hiragana

from okinawago_dictionary.dictionary import Dictionary, oki_dict, yamato_dict, katsuyou_jiten


class Match(NamedTuple):
    dict_type: str
    dict_type_for_display: str
    matched_ids: List[int]
    matched_words: List[str]
    matched_words_for_display: Optional[List[str]] = None


def _get_dict(dict_type: str) -> Dictionary:
    if dict_type == 'oki2yamato':
        return oki_dict
    elif dict_type == 'katsuyou_jiten':
        return katsuyou_jiten
    elif dict_type == 'yamato2oki':
        return yamato_dict
    else:
        raise NotImplementedError


Filter = Callable[[str], bool]
Sorter = Callable[[List[Match]], List[Match]]


def _get_filter(word: str, search_type: str) -> Filter:
    if search_type == 'contains':

        def filter_(key: str) -> bool:
            return word in key
    elif search_type == "startswith":

        def filter_(key: str) -> bool:
            return key.startswith(word)
    elif search_type == "endswith":

        def filter_(key: str) -> bool:
            return key.endswith(word)

    return filter_


def _emphasize_match(match: Match, str_to_emph: str) -> Match:
    if match.dict_type == "yamato2oki":
        str_to_emph = to_hiragana(str_to_emph)
    pattern = re.compile(r"(" + str_to_emph + r")")
    return Match(
        match.dict_type, match.dict_type_for_display, match.matched_ids,
        match.matched_words,
        [pattern.sub(r"<b>\1</b>", word) for word in match.matched_words])


def _get_sorter(search_type: str, word: str, normaliser) -> Sorter:
    if search_type == 'contains':

        def _key_func(match: Match):
            matched_words = [normaliser(word) for word in match.matched_words]
            matched_index, distance = min(map(
                lambda w: (w, len(re.sub(word, '', w))), matched_words),
                                          key=lambda x: x[1])
            index = matched_index.index(word)
            return (index, distance, matched_index)

        def _sort(word_list: List[Match]) -> List[Match]:
            return sorted(word_list, key=_key_func)
    else:

        def _sort(word_list: List[Match]) -> List[Match]:
            return sorted(
                word_list,
                key=lambda m: oki_dict.normalise_kana(m.matched_words[0]))

    return _sort


dict_types = {'oki2yamato': '沖', 'yamato2oki': '日', 'katsuyou_jiten': 'う'}


def get_results(
    dict_type: str,
    dictionary: Dictionary,
    match_filter: Filter,
) -> List[Match]:
    matched_words: Dict[Tuple[int, ...], List[str]] = {}
    for candidate_word in dictionary.index_words:
        if match_filter(candidate_word):
            matched_ids = tuple(dictionary.get_keys(candidate_word))
            words_with_same_ids = matched_words.setdefault(matched_ids, [])
            matched_words[matched_ids] = words_with_same_ids + [candidate_word]
    return [
        Match(dict_type, dict_types[dict_type], list(ids), indices)
        for ids, indices in matched_words.items()
    ]


def search(
    query_word: str,
    search_type: str,
    dict_types: List[str],
) -> List[Match]:
    matched_results = []
    sort_func = _get_sorter(search_type, oki_dict.normalise_kana(query_word),
                            oki_dict.normalise_kana)
    for dict_type in dict_types:
        dictionary = _get_dict(dict_type)
        match_filter = _get_filter(dictionary.normalise_kana(query_word),
                                   search_type)
        matched_results += get_results(dict_type, dictionary, match_filter)
    return [
        _emphasize_match(match, oki_dict.normalise_kana(query_word))
        for match in sort_func(matched_results)
    ]


def get_contents(key_word: str, dict_type: str):
    dictionary = _get_dict(dict_type)
    key_word = key_word.replace("\u2003", "").replace(" ", "")
    key_word = dictionary.normalise_kana(key_word)
    keys = dictionary.get_keys(key_word)
    if not keys:
        return []
    return [dictionary.get_content(key) for key in keys]
