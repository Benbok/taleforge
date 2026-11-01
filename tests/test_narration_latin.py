from app.agents.master.exploration import latin_words


def test_latin_in_the_prose_is_found_but_the_ids_of_links_are_not():
    assert latin_words("Кулак вошёл в серую flesh... нет, плоть.") == ["flesh"]
    assert latin_words("[[en_15624a02c6c4b1978de0221b|Тень]] качнулась у [[ch_bfe2|Соры]].") == []


def test_a_leftover_placeholder_is_a_slip_too():
    assert latin_words("Старик смотрел на Сору; <...> Тень лежала.") == ["<...>"]
