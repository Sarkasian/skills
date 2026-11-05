from pkg.pricing import calc_total


def cart_total(cart):
    return calc_total([i["price"] for i in cart], 0.2)
