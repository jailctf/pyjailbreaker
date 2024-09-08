"""
Gadgets that work the same as subscripting a dictionary / `dict.__getitem__`.
"""

def dict_getitem__get(dict, key):
    return dict.get(key)

def dict_getitem__attrerror(dict, key):
    try:
        f"{{{key}.xx}}".format_map(dict)
    except Exception as e:
        return e.obj