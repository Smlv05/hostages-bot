from collections import Counter

import pytest

from game import Game, Team, build_deck


def make_full_game(size: int) -> Game:
    game = Game(chat_id=1, host_id=1, size=size)
    for uid in range(size):
        game.add_player(uid, f"player{uid}")
    return game


@pytest.mark.parametrize("size", [8, 10])
def test_unique_roles_except_civilians(size):
    counts = Counter(r.key for r in build_deck(size))
    for key, count in counts.items():
        if "civilian" not in key:
            assert count == 1, key
    assert len(build_deck(size)) == size


def test_no_civilians_in_8():
    assert not any("civilian" in r.key for r in build_deck(8))


def test_civilians_in_10():
    keys = [r.key for r in build_deck(10)]
    assert keys.count("blue_civilian") == 1 and keys.count("red_civilian") == 1


@pytest.mark.parametrize("size", [7, 9, 12])
def test_invalid_sizes(size):
    with pytest.raises(ValueError):
        build_deck(size)


def test_spies_have_opposite_card_color():
    deck = {r.key: r for r in build_deck(8)}
    assert deck["blue_spy"].team is Team.BLUE and deck["blue_spy"].card_color is Team.RED
    assert deck["red_spy"].team is Team.RED and deck["red_spy"].card_color is Team.BLUE


@pytest.mark.parametrize("size", [8, 10])
def test_start_gives_everyone_role_and_splits_tables(size):
    game = make_full_game(size)
    game.start()
    assert all(p.role for p in game.players.values())
    assert len(game.table(1)) == len(game.table(2)) == size // 2


def test_cannot_overfill_or_join_twice():
    game = Game(chat_id=1, host_id=1, size=8)
    assert game.add_player(1, "a")
    assert not game.add_player(1, "a")
    for uid in range(2, 9):
        game.add_player(uid, "x")
    assert not game.add_player(99, "late")


def test_four_rounds_only():
    game = make_full_game(8)
    game.start()
    assert [game.next_round() for _ in range(5)] == [1, 2, 3, 4, None]