"""
Gadgets for obtaining the `bytes` type.
"""


def bytes__str(*, type, str):
    return type(str().encode())

def bytes__type(*, type):
    return type(b'')

def bytes__dunder_class():
    return b''.__class__

def bytes__gen(*, type):
    return type((i for i in []).gi_code.co_code)

def bytes__lambda(*, type):
    return type((lambda:0).__code__.co_code)