"""Train/test split assignment, locked and idempotent once assigned
(module spec §7/§12)."""

import random


def assign_split(user_ids: list, train_fraction: float, seed: int, existing: dict = None) -> dict:
    """
    Returns a {user_id: "train"|"test"} mapping. Ids already present in
    `existing` keep their assignment unchanged; only new ids are shuffled
    (deterministically, via `seed`) and split by `train_fraction`.
    """
    existing = dict(existing or {})
    new_ids = [uid for uid in user_ids if uid not in existing]

    shuffled = new_ids[:]
    random.Random(seed).shuffle(shuffled)
    cutoff = round(len(shuffled) * train_fraction)

    result = dict(existing)
    for uid in shuffled[:cutoff]:
        result[uid] = "train"
    for uid in shuffled[cutoff:]:
        result[uid] = "test"
    return result
