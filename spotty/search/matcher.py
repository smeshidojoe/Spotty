"""
Нечёткое сравнение запроса с названием.

Порядок важности — как у Spotlight: точное совпадение, начало названия, начало
слова, первые буквы слов («vsc» -> Visual Studio Code), подстрока, и в конце
буквы по порядку с пропусками. Запрос из нескольких слов подходит, только
если подходит каждое слово.

Запрос, набранный не в той раскладке («ишщ» вместо «bio»), тоже находит своё.
"""

import re
from functools import lru_cache

_EN = "`qwertyuiop[]asdfghjkl;'zxcvbnm,./"
_RU = "ёйцукенгшщзхъфывапролджэячсмитьбю."
_TO_RU = str.maketrans(_EN, _RU)
_TO_EN = str.maketrans(_RU, _EN)

_WORD_SPLIT = re.compile(r"[^0-9a-zа-яё]+")
_CAMEL = re.compile(r"(?<=[a-zа-яё])(?=[A-ZА-ЯЁ])")


def other_layout(query):
    """Тот же набор клавиш в другой раскладке или None, если менять нечего."""
    if not query:
        return None
    has_ru = any("а" <= c <= "я" or c == "ё" for c in query)
    has_en = any("a" <= c <= "z" for c in query)
    if has_ru and not has_en:
        return query.translate(_TO_EN)
    if has_en and not has_ru:
        return query.translate(_TO_RU)
    return None


def words(name):
    """Слова названия с учётом camelCase: 'OneDrive Setup' -> ['one', 'drive', 'setup']."""
    return [w for w in _WORD_SPLIT.split(_CAMEL.sub(" ", name).lower()) if w]


def _token_score(token, name, name_words, initials):
    if name == token:
        return 100.0
    if name.startswith(token):
        return 90.0 - min(len(name) - len(token), 20) * 0.2
    for i, word in enumerate(name_words):
        if word.startswith(token):
            return 80.0 - i
    if len(token) >= 2 and initials.startswith(token):
        return 75.0
    pos = name.find(token)
    if pos >= 0:
        return 60.0 - min(pos, 20) * 0.5
    return _subsequence(token, name, name_words)


def _subsequence(token, name, name_words):
    """
    Буквы запроса по порядку с пропусками: 'chrm' в 'Google Chrome'.

    Первая буква обязана начинать слово, а пропусков — не больше длины
    запроса плюс один (так ещё проходят «ntpd» и «phsp»). Иначе «tele»
    находил бы «QuickTime Player»: t, e, l, e там тоже идут по порядку, но
    совпадением это никто не назовёт.
    """
    if len(token) < 3:
        return 0.0
    best = 0.0
    start = 0
    for word in name_words:
        start = name.find(word, start)
        if start < 0 or word[0] != token[0]:
            start = max(start, 0) + len(word)
            continue
        pos, gaps, last = start, 0, -1
        for ch in token:
            pos = name.find(ch, pos)
            if pos < 0:
                gaps = None
                break
            if last >= 0:
                gaps += pos - last - 1
            last = pos
            pos += 1
        if gaps is not None and gaps <= len(token) + 1:
            best = max(best, 40.0 - gaps)
        start += len(word)
    return best


@lru_cache(maxsize=8192)
def _prepared(name):
    """
    Нижний регистр, слова и первые буквы названия. Считаются один раз: на
    каждое нажатие сравниваются сотни названий, и разбирать их регулярными
    выражениями заново — половина всего времени поиска.
    """
    name_words = words(name)
    return name.lower(), name_words, "".join(w[0] for w in name_words)


def score(query, name):
    """0 — не подходит; больше — лучше. query уже в нижнем регистре."""
    lower, name_words, initials = _prepared(name)
    tokens = query.split()
    if not tokens:
        return 0.0
    total = 0.0
    for token in tokens:
        s = _token_score(token, lower, name_words, initials)
        if s <= 0:
            return 0.0
        total += s
    return total / len(tokens)


def best_score(query, alt_query, name):
    """Лучший из запроса как есть и запроса в другой раскладке."""
    s = score(query, name)
    if alt_query:
        # Своя раскладка чуть важнее: «сщву» вероятнее опечатка, чем название.
        s = max(s, score(alt_query, name) * 0.95)
    return s
