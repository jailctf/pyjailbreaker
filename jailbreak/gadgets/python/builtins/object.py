"""
Gadgets for obtaining the `object` type.
"""

def object__type_mro(*, type):
    return type.mro(type)[1]

# works for all builtin classes EXCEPT type
def object__class_mro(*, cls):
    return cls.mro()[-1]


#unlikely that tuple would be unavailable specifically in scenarios where we can use __base__ anyway,
#no need for other base types hopefully
def object__tuple_base():
    return ().__class__.__base__