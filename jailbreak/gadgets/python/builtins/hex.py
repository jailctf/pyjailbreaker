"""
Gadgets that work the same as the builtin function `chr`.
"""

def hex__fmt_str(num):
    return f'{num:#x}'

def hex__format(num):
    return '{:#x}'.format(num)

def hex__builtins(num, *, builtins_dict):
    return builtins_dict['hex'](num)