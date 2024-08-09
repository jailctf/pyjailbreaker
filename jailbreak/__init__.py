import ast, os, importlib, inspect
import asttokens
from . import converters, utils, gadgets

_registered_converters = {n: [] for a in ast.AST.__subclasses__() for n in a.__subclasses__()}

_set_config = {'restrictions': {}, 'provided': []}


def config(**kwargs):
    global _set_config

    #put provided in another field since it is not a restriction
    _set_config['provided'] = kwargs.pop('provided')

    _set_config['restrictions'] = kwargs


#for use as decorator on converters
#TODO probably convert this into a self walking ast tree
def register_converter(*nodes):
    def apply(converter):
        for n in nodes:
            _registered_converters[n].append(converter)
        return converter

    return apply


def _exempt_node(node, required_gadgets, func_name):
    #top level ast node, generated on ast.parse
    if isinstance(node, ast.Module):
        return True

    #main gadget declaration, ignore
    if isinstance(node, ast.FunctionDef) and node.name == func_name:
        return True
    
    #using gadgets, ignore
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in required_gadgets:
        return True

    return False
        

def _count_violations(func, required_gadgets) -> int:
    func_src = inspect.getsource(func)
    ast_tree = asttokens.ASTTokens(func_src, parse=True)
    all_nodes = [n for n in ast.walk(ast_tree.tree) if not _exempt_node(n, required_gadgets, func.__name__)]
    
    #handle manual information
    checks = {}
    if func.__doc__ != None:
        for line in func.__doc__.splitlines():
            field, val = line.strip().split(':', 1)
            checks[field] = ast.literal_eval(val)

    #handle automatic information
    checks['ast'] = {type(n) for n in all_nodes}
    checks['char'] = {c for n in all_nodes if hasattr(n, 'first_token') for tok in ast_tree.token_range(n.first_token, n.last_token) for c in tok.string}
    #TODO also make a substring check instead of just char

    violations = set()
    for field, restrictions in _set_config['restrictions'].items():
        violations |= set(restrictions).intersection(set(checks[field]))

    return violations


def _try_gadget(name: str, all_gadgets: dict, seen: list):
    #terminate if provided
    if name in _set_config['provided']:
        return (f'#def {name}(*args, **kwargs): pass  #TODO provided\n\n', lambda: ...)  #any empty func would work

    for gadget, func in all_gadgets.items():
        if gadget in seen:
            continue

        if gadget.startswith(name):
            #print('trying', gadget)

            fullargspec = inspect.getfullargspec(func)
            required_gadgets = fullargspec.kwonlyargs
            violations = _count_violations(func, required_gadgets)
            if not violations:
                func_src_user = inspect.getsource(func).splitlines()
                func_src_user[0] = f'def {gadget}({", ".join(fullargspec.args)}):'   #replace the header to exclude gadget use
                func_src_user = '\n'.join(func_src_user) + '\n'
                func_src_user += f'{name} = {gadget}'  #tell the user we are using this specific gadget for the gadget they want
                if not fullargspec.args:
                    func_src_user += '()'  #call the gadget to convert it to an attr access
                func_src_user += '\n\n'

            
                if not required_gadgets:   #no more to chain, return (base case)
                    return (func_src_user, func)
                
                good = True
                for next_gadget in required_gadgets:
                    next_src, _ = _try_gadget(next_gadget, all_gadgets, seen + [gadget])

                    #(at least) one of the required gadgets does not have a valid chain, drop out
                    if not next_src:
                        good = False
                        break
                    
                    func_src_user = next_src + func_src_user  #so the order is more human readable (earlier gadgets are at the top)
                
                if good:
                    return (func_src_user, func)  #generated code so far, current gadget func
    
    return (None, None) #could be due to a gadget requiring an unknown gadget



del __path__  #prevent __getattr__ from running twice

#chain searcher, only runs if the name is not in scope
def __getattr__(name):
    if name == '__path__':
        raise AttributeError("path doesn't exist on the jailbreak module")
    
    try:
        #enable from jailbreak import * syntax
        if name == '__all__':
            return ['config', 'register_converter', 'converters', 'utils', 'gadgets']

        gadgets_path = gadgets.__path__[0]

        gadget_type = None
        for path, _, filenames in os.walk(gadgets_path):
            for f in filenames:
                if f.lower() == name + '.py':
                    gadget_type = os.path.relpath(path, gadgets_path).split(os.sep)[0]
                    break

        if gadget_type == None: raise NameError(f'gadget {name} not found!')
        
        #recursively obtain all gadgets of the same type
        all_gadgets = {}
        for path, _, filenames in os.walk(gadgets_path + os.sep + gadget_type):
            for f in filenames:
                filename, ext = os.path.splitext(f)
                if ext.lower() == '.py':
                    #import the gadget file as a module
                    gadget_module = importlib.import_module('.' + os.path.relpath(path, gadgets_path).replace(os.sep, '.') + '.' + filename, gadgets.__name__)
                    for attrname in dir(gadget_module):
                        if attrname.startswith(filename):
                            all_gadgets[attrname] = getattr(gadget_module, attrname)

        if gadget_type == 'python':  #returning just the string for python based chain is good
            chain, gadget_func = _try_gadget(name, all_gadgets, [])
            
            if not chain: return None

            params = inspect.getfullargspec(gadget_func).args
            def param_wrapper(*args):
                nonlocal chain
                chain += f'{name}'
                if params: 
                    chain += f'({", ".join(args)})'
                return chain + '\n'

            return param_wrapper
        else:
            return exec(chain) #apply restrictions and obtain bytes; works fairly differently from python gadget chains
    except Exception as e:
        import traceback
        traceback.print_exc()