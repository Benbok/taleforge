from app.agents.master.prompting.lore import select_blocks, split_lore, stems


def test_split_makes_blocks_with_stable_ids():
    world = {"laws": "Двери держат тепло.\n\nЗал всегда открыт.", "powers": "Свет бывает волшебным."}
    blocks = split_lore(world)
    assert [block.id for block in blocks] == ["laws:0", "laws:1", "powers:0"]
    assert split_lore(world) == blocks
    assert all(block.title and len(block.summary) <= 120 for block in blocks)


def test_stems_match_russian_forms():
    assert stems("дверь") & stems("двери") & stems("дверью")
    assert stems("зал") & stems("залу")
    assert stems("запертый") & stems("запертую")
    assert stems("Ёлки") == stems("елки")
    assert not stems("и на к")


def test_relevant_block_is_selected_by_the_players_words():
    blocks = split_lore({"laws": "Дверь открывается ключом.\n\nРеактор требует охлаждения."})
    index, selected = select_blocks(blocks, "иду к двери", 100)
    assert [block.id for block in selected] == ["laws:0"]
    assert len(index) == 2


def test_budget_limits_full_blocks_and_keeps_the_whole_index():
    blocks = split_lore({"laws": "Двери заперты.\n\nДвери тяжёлые."})
    index, selected = select_blocks(blocks, "дверь", len(blocks[0].text))
    assert len(index) == 2
    assert len(selected) == 1
    assert sum(len(block.text) for block in selected) <= len(blocks[0].text)
    assert select_blocks(blocks, "дверь", 0)[1] == []


def test_empty_world_gives_no_blocks_and_no_error():
    assert split_lore({}) == []
    assert split_lore({"powers": None}) == []
    assert select_blocks([], "идём", 1500) == ([], [])
