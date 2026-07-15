from __future__ import annotations

from collections import Counter


def bigram_similarity(left: str, right: str) -> float:
    def grams(value: str) -> Counter:
        return Counter(value[index : index + 2] for index in range(len(value) - 1))

    a = grams(left)
    b = grams(right)
    overlap = sum(min(count, b.get(gram, 0)) for gram, count in a.items())
    return (2 * overlap) / max(1, len(left) + len(right) - 2)
