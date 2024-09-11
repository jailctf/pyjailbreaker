"""
Gadgets that work the same as the builtin function `getattr`.
"""

def getattr__vars(obj, attr, *, vars):
    return vars(obj)[attr]

def getattr__dict(obj, attr):
    return obj.__dict__[attr]

def getattr__try_attrerror(obj, attr, *, Exception):
    try:
        #TODO format string to f-stringless converter for strless converter to remove dependency on `{}`
        f'{{0.{attr}.xx}}'.format(obj)
    except Exception as e:
        return e.obj
    
def getattr__with_attrerror(obj, attr, *, type):
    exit_fn = lambda self, exc_type, exc_value, tb: [1 for self.attr in [exc_value.obj]]
    a = type('', (), {'__enter__': lambda *args: None, '__exit__': exit_fn})()
    try:
        with a: f"{{0.{attr}.xx}}".format(obj)
    except: pass
    return a.attr