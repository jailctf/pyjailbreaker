"""
Gadgets for obtaining the `bool` type.
"""

def bool__dunder_class():
    return True.__class__

def bool__type(*, type):
    return type(True)

def bool__dunder_class_num():
    return (1<2).__class__

def bool__type_num(*, type):
    return type(1<2)