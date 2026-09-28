from spotty.search import matcher


def rank(query, names):
    alt = matcher.other_layout(query)
    scored = [(matcher.best_score(query, alt, n), n) for n in names]
    return [n for s, n in sorted(scored, key=lambda r: -r[0]) if s > 0]


def test_exact_beats_prefix_beats_word_start():
    names = ["Telegram Desktop", "Tel", "Hotel Manager"]
    assert rank("tel", names) == ["Tel", "Telegram Desktop", "Hotel Manager"]


def test_initials():
    assert matcher.score("vsc", "Visual Studio Code") > 0


def test_letters_in_order():
    assert matcher.score("ntpd", "Notepad") > 0
    assert matcher.score("chrm", "Google Chrome") > 0


def test_scattered_letters_are_not_a_match():
    # t, e, l, e идут по порядку и в «QuickTime Player», но это не совпадение.
    assert matcher.score("tele", "QuickTime Player") == 0


def test_every_word_must_match():
    assert matcher.score("visual code", "Visual Studio Code") > 0
    assert matcher.score("visual chrome", "Visual Studio Code") == 0


def test_wrong_keyboard_layout():
    assert matcher.other_layout("еудупкфь") == "telegram"
    assert matcher.other_layout("ghbdtn") == "привет"
    assert rank("еудупкфь", ["Telegram", "Steam"]) == ["Telegram"]


def test_own_layout_wins_over_other():
    # «Сщву» набрано по-русски — своя раскладка чуть важнее.
    alt = matcher.other_layout("code")
    assert matcher.best_score("code", alt, "Code") > matcher.best_score("code", alt, "Сщву")


def test_prepared_names_are_cached():
    matcher.score("x", "Some Long Application Name")
    before = matcher._prepared.cache_info().hits
    matcher.score("y", "Some Long Application Name")
    assert matcher._prepared.cache_info().hits == before + 1
