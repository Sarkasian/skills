from pkg import pricing


def invoice_total(lines):
    return pricing.calc_total([l["amount"] for l in lines], 0.0)
