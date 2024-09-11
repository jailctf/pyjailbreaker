"""
Gadgets for obtaining the `int` type.
"""

def int__bool_mro(*, bool):
    return bool.mro()[1]

def int__type(*, type):
    return type(0)

def int__bool_type(*, type):
    return type(-True)

def int__dunder_class():
    return (0).__class__

def int__bool_dunder_class():
    return (-True).__class__