"""
Gadgets for obtaining a list of all loaded classes.
"""


#basic subclasses trick
def list_classes__obj_subclass(*, object):
    return object.__subclasses__()