"""Cart."""


def count(items):
    return sum(qty for _, qty in items)
