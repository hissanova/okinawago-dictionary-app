from typing import Callable, Dict, List, NamedTuple, Tuple

from okinawago_dictionary.dictionary import Dictionary, oki_dict, yamato_dict, katsuyou_jiten


def _get_dict(dict_type: str) -> Dictionary:
    if dict_type == 'oki2yamato':
        return oki_dict
    elif dict_type == 'katsuyou_jiten':
        return katsuyou_jiten
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


class Match(NamedTuple):
    dict_type: str
    display_str: str
    matched_ids: List[int]
    matched_words: List[str]


def _sort(word_list: List[Match]) -> List[Match]:
    return sorted(word_list, key=lambda m: m.matched_words[0])


display_str = {'oki2yamato': '沖日', 'yamato2oki': '日沖', 'katsuyou_jiten': 'うち活'}


def get_results(dict_type, dictionary, match_filter):
    matched_words: Dict[Tuple[int, ...], List[str]] = {}
    for candidate_word in dictionary.index_words:
        if match_filter(candidate_word):
            matched_ids = tuple(dictionary.get_keys(candidate_word))
            words_with_same_ids = matched_words.setdefault(matched_ids, [])
            matched_words[matched_ids] = words_with_same_ids + [candidate_word]
    return [
        Match(dict_type, display_str[dict_type], list(ids), indices)
        for ids, indices in matched_words.items()
    ]


def search(
    query_word: str,
    search_type: str,
    dict_type: str,
    use_katsuyou_jiten: bool,
) -> List[Match]:
    dictionary = _get_dict(dict_type)
    match_filter = _get_filter(dictionary.normalise_kana(query_word),
                               search_type)
    matched_results = get_results(dict_type, dictionary, match_filter)
    print(matched_results[:5])
    if use_katsuyou_jiten:
        matched_results += get_results('katsuyou_jiten', katsuyou_jiten,
                                       match_filter)
    return _sort(matched_results)


def get_contents(key_word: str, dict_type: str):
    dictionary = _get_dict(dict_type)
    keys = dictionary.get_keys(key_word)
    if not keys:
        return []
    return [dictionary.get_content(key) for key in keys]
