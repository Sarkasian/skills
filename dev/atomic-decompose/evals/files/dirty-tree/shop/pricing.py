"""Prices."""


def net(price, vat=0.19):
    return round(price / (1 + vat), 2)
