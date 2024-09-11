"""
Gadgets for obtaining the `str` type.
"""

def str__type(*, type):
    return type('')

def str__dunder_class():
    return ''.__class__

def str__bytes(*, type, bytes):
    return type(bytes().decode())

def str__gen(*, type):
    return type((x for x in ()).gi_code.co_name)

# your chal gotta be evil asf if you have to resort to this
def str__kwargs(*, type):
    return type(*(lambda**k:k)(l=1))