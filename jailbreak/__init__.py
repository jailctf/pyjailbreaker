import ast
from . import converters, utils, gadgets

_registered_converters = {n: [] for a in ast.AST.__subclasses__() for n in a.__subclasses__()}

_set_config = {}


def config(**kwargs):
    global _set_config
    _set_config = kwargs

#for use as decorator on converters
def register_converter(*nodes):
    def apply(converter):
        for n in nodes:
            _registered_converters[n].append(converter)
        return converter

    return apply


#chain searcher, only runs if the name is not in scope
def __getattr__(name):    
    if name == '__all__':
        return ['config', 'register_converter', 'converters', 'utils', 'gadgets']

    #TODO else search for gadget name and traverse    
    #remember to avoid cyclic graph, terminate on same gadget visited again

    #if gadget type is python/pwn, convert into ast and generate code
    #if gadget type is pickle/bytecode, run the gadget chain generated

    return name