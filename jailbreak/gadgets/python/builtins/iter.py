"""
Gadgets that work the same as the builtin function `iter`.
"""

def iter__attrerror(seq, *, Exception):
    try:
        def hm():
            yield from seq
        g = hm()
        g.send(None)
        g.send(1)
    except Exception as e:
        return e.obj
    
def iter__builtins(seq, *, builtins_dict):
    return builtins_dict['iter'](seq)