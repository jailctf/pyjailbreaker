"""
Gadgets for obtaining the os module.
"""

def os__sys(*, sys):
    return sys.modules['os']

def os__import(*, import_builtin_module):
    return import_builtin_module('os')