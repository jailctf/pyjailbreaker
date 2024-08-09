"""
Gadgets for obtaining the os module.
"""

def os__sys(*, sys):
    return sys.modules['os']

def os__import(*, __import__):
    return __import__('os')

def os__loader(*, __loader__):
    return __loader__.load_module('os')