import json
import os
import random

from generator import _luhn_card, build_customers, write_days


def luhn_ok(number):
    total = 0
    for i, d in enumerate(int(x) for x in reversed(number)):
        if i % 2 == 1:
            d *= 2
            d -= 9 if d > 9 else 0
        total += d
    return total % 10 == 0


def read_dir(path):
    return {name: open(os.path.join(path, name)).read() for name in sorted(os.listdir(path))}


def test_card_numbers_pass_luhn():
    rng = random.Random(0)
    assert all(luhn_ok(_luhn_card(rng)) for _ in range(1_000))


def test_customers_are_deterministic():
    assert build_customers(42) == build_customers(42)


def test_incremental_run_matches_full_run(tmp_path):
    full, split = tmp_path / "full", tmp_path / "split"
    write_days(str(full), 4)
    assert write_days(str(split), 2) == (0, 1)
    assert write_days(str(split), 2) == (2, 3)
    for folder in ("transactions", "customers", "merchants"):
        assert read_dir(full / folder) == read_dir(split / folder)


def test_private_fields_are_not_written(tmp_path):
    write_days(str(tmp_path), 1)
    for folder in ("customers", "transactions"):
        for content in read_dir(tmp_path / folder).values():
            for line in content.splitlines():
                assert not any(k.startswith("_") for k in json.loads(line))
