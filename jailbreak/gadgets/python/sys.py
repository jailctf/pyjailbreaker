"""
Gadgets for obtaining the sys module.
"""

def sys__wrap_close(*, list_classes, str):
    return [c for c in list_classes if 'wrap_close' in str(c)][0].__init__.__globals__['sys']

def sys__import(*, import_builtin_module):
    return import_builtin_module('sys')