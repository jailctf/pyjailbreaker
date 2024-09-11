"""
Gadgets that work the same as the builtin function `chr`.
"""


def chr__bytes(n, *, bytes):
    return bytes([n]).decode()

def chr__fmt_str(n):
    return f'{n:c}'

def chr__format(n):
    return '{:c}'.format(n)

def chr__builtins(n, *, builtins_dict):
    return builtins_dict['chr'](n)