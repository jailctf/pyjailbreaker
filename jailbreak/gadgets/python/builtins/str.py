"""
Gadgets for obtaining the `str` type.
"""


def str__type(*, type):
    return type('')


def str__gen(*, type):
    return type((x for x in ()).gi_code.co_name)