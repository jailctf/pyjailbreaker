"""
Gadgets that work the same as the builtin function `__import__`, but only guaranteed to work for builtin modules
(slight difference - gadgets here will only conform to the single parameter version of `__import__`)
"""


def import_builtin_module__builtinimporter(mod, *, list_classes, str):
    return [c for c in list_classes if 'BuiltinImporter' in str(c)][0].load_module(mod) 


#TODO extract the ways to create a fake object with given attrs into another gadget?
def import_builtin_module__imp_class(mod, *, sys):
    class fake():
        name = mod
    return sys.modules['_imp'].create_builtin(fake())


def import_builtin_module__imp_func(mod, *, sys):
    #no idea why if we dont have this comment inspect.getsource() will return only the lambda line for this gadget
    fake = lambda: ...
    fake.name = mod
    return sys.modules['_imp'].create_builtin(fake)

#simplest, but with side effects (that prob doesnt matter)
def import_builtin_module__imp_mod(mod, *, sys):
    sys.name = mod
    return sys.modules['_imp'].create_builtin(sys)

def import_builtin_module__loader(mod, *, sys):
    return sys.__loader__.load_module(mod)