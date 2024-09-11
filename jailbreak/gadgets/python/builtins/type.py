"""
Gadgets for obtaining the `type` type.
"""

def type__class():
    return [].__class__.__class__

#from abc import ABCMeta
def type_abcmeta(*, ABCMeta):
    return ABCMeta.mro(ABCMeta)[1]