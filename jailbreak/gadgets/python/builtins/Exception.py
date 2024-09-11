"""
Gadgets for obtaining the `Exception` type.
"""

def Exception__builtin(*, builtins_dict):
    return builtins_dict['Exception']

# would be used in a situation where you aren't allowed underscores (ones in string would be escaped)
def Exception__with_type(*, type):
    exit_fn = lambda self, exc_type, exc_value, tb: [1 for self.exc in [exc_type.mro()[2]]]
    a = type('', (), {'__enter__': lambda *args: None, '__exit__': exit_fn})()
    try:
        with a: 1/0
    except: pass
    return a.exc

# more general case
def Exception__with_class():
    class A:
        def __enter__(self):
            pass
        
        def __exit__(self, exc_type, exc_value, tb):
            self.exc = exc_type.mro()[2]
            
    a = A()
    try:
        with a: 1/0
    except: pass
    return a.exc