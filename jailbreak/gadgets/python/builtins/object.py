"""
Gadgets for obtaining the `object` type.
"""


def object__type_mro(*, type):
    return type()(type()).mro(type())[1]


#unlikely that tuple would be unavailable specifically in scenarios where we can use __base__ anyway,
#no need for other base types hopefully
def object__tuple_base():
    return ().__base__