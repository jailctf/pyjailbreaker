"""
Gadgets for obtaining the os module
"""

def get_os__sys(*, get_sys):
    return get_sys().modules['os']

def get_os__import(*, __import__):
    return __import__()('os')

def get_os__loader(*, __loader__):
    return __loader__().load_module('os')