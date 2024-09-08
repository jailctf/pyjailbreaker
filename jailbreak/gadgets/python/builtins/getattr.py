"""
Gadgets that work the same as the builtin function `getattr`.
"""

def getattr__vars(obj, attr, vars):
    return vars(obj)[attr]

def getattr__dict(obj, attr):
    return obj.__dict__[attr]

def getattr__attrerror(obj, attr):
    try:
        #TODO format string to f-stringless converter for strless converter to remove dependency on `{}`
        f'{{0.{attr}.xx}}'.format(obj)
    except Exception as e:
        return e.obj