#avoid polluting the normal getattr space
import ast as _ast, os as _os, importlib as _importlib, inspect as _inspect, itertools as _itertools
from types import FunctionType as _FunctionType

_registered_converters = {n: [] for a in _ast.AST.__subclasses__() for n in a.__subclasses__()} | {n: [] for n in _ast.AST.__subclasses__()}
_applicable_converters = {}

_set_config = {'restrictions': {}, 'provided': []}
_user_gadgets = {}


def config(**kwargs):
    global _set_config

    #put provided in another field since it is not a restriction
    _set_config['provided'] = kwargs.pop('provided', [])

    _set_config['restrictions'] = kwargs


#for adding custom gadgets by the user
def register_user_gadget(func):
    _user_gadgets[func.__name__] = func


#for use as decorator on converters
def register_converter(*nodes, **violations):
    def apply(converter):
        #we dont really care about the type since violations are reported as a set of all violations anyway
        for type, list in violations.items():
            for violation in list:
                if violation in _applicable_converters:
                    _applicable_converters[violation].append(converter)
                else:
                    _applicable_converters[violation] = [converter]

        for n in nodes:
            _registered_converters[n].append(converter)
        return converter

    return apply


#ast walker for applying given converters
class ApplyConverter(_ast.NodeTransformer):
    def __init__(self, converter: _FunctionType) -> None:
        super().__init__()
        #change the converter so that the gadgets in kwonlyargs are not required to call the func
        self.converter = _FunctionType(converter.__code__.replace(co_kwonlyargcount=0), converter.__globals__)
        self.orig = converter
    
    def generic_visit(self, node: _ast.AST) -> _ast.AST:
        #compare the original object since self.converter is a new object now
        if self.orig in _registered_converters[type(node)]:
            node = _ast.fix_missing_locations(self.converter(node))
        
        #otherwise return itself
        return super().generic_visit(node)


#required since there could be variable naming clashes that break a gadget if its not nested
#XXX assumes func definition is at the top line and only consists of a single line
#XXX assumes code are indented every 4 spaces
def _put_code_into_func_body(func_src: str, code_src: str):
    func_src = func_src.splitlines()
    code_src = ['    ' + line for line in code_src.splitlines()]
    return '\n'.join([func_src[0]] + code_src + func_src[1:]) + '\n'


def _exempt_node(node, required_gadgets, func_name):
    #top level _ast node, generated on _ast.parse
    if isinstance(node, _ast.Module):
        return True

    #main gadget declaration, ignore
    if isinstance(node, _ast.FunctionDef) and node.name == func_name:
        return True
    
    #using gadgets, ignore
    if isinstance(node, _ast.Call) and isinstance(node.func, _ast.Name) and node.func.id in required_gadgets:
        return True

    return False
        

def _count_violations(func, required_gadgets, func_src=None) -> int:
    import asttokens

    if not func_src:  #only getsource if we didnt provide it, since _ast rewritten funcs do not have getsource
        func_src = _inspect.getsource(func)
    ast_tree = asttokens.ASTTokens(func_src, parse=True)
    all_nodes = [n for n in _ast.walk(ast_tree.tree) if not _exempt_node(n, required_gadgets, func.__name__)]
    
    #handle manual information
    checks = {}
    if func.__doc__ != None:
        for line in func.__doc__.splitlines():
            field, val = line.strip().split(':', 1)
            checks[field] = _ast.literal_eval(val)

    #handle automatic information
    checks['ast'] = {type(n) for n in all_nodes}
    checks['char'] = {c for n in all_nodes if hasattr(n, 'first_token') for tok in ast_tree.token_range(n.first_token, n.last_token) for c in tok.string}
    #TODO also make a substring check instead of just char

    violations = set()
    for field, restrictions in _set_config['restrictions'].items():
        violations |= set(restrictions).intersection(set(checks[field]))

    return violations

def _choose_converter_for_violation(violation, gadget: str, all_gadgets: dict, seen: list):
    #choose first one that would succeed under our jail (there is no point in trying other converters if this one succeeds, assuming the kwargs annotations via @register_converter accurately depicts what the converter does)
    for converter in _applicable_converters[violation]:
        converter_required_gadgets = _inspect.getfullargspec(converter).kwonlyargs
        for next_gadget in converter_required_gadgets:
            chain, _ = _try_gadget(next_gadget, all_gadgets, seen + [gadget])
            if chain:
                return (converter, chain)
                
def _try_convert(func_src_user: str, required_gadgets: list, violations: list, gadget: str, all_gadgets: dict, seen: list):
    #obtain a list of all converters that we should run to avoid the violations
    converters_to_run = set()
    generated_chains_for_converters = {}
    for violation in violations:
        if violation in _applicable_converters and _applicable_converters[violation]:
            converter, chain = _choose_converter_for_violation(violation, gadget, all_gadgets, seen)
            generated_chains_for_converters[converter] = chain
            converters_to_run.add(converter)
        else:
            return (None, None)  #not all violations can be converted away, give up on this chain

    #XXX dumb heuristic - try all converter application orders to see if any can actually achieve no violations
    #XXX situations where e.g. the strless converter uses chr(), which introduces CALLs and requires callless converter to run on it yet no CALLs were in the main gadget will just fail with this method
    #XXX but if we are lucky (eg main gadget has CALL violations so callless converter is in converters_to_run) then the conversion will pass
    for apply in _itertools.permutations(converters_to_run):
        ast_tree = _ast.parse(func_src_user)
        #remove kwonlyargs from the function def coz its not actually part of the function
        ast_tree.body[0].args.kwonlyargs = []
        for converter in apply:
            ast_tree = ApplyConverter(converter).visit(ast_tree)
        func_src_user = _ast.unparse(ast_tree) + '\n'
        func = _FunctionType(compile(func_src_user, '<string>', 'exec').co_consts[0], globals())
        #XXX we are assuming converters do not introduce new regressions, otherwise we will have to rerun the whole conversion test again when we see violations
        if not _count_violations(func, required_gadgets, func_src_user):
            #add the required gadget chain(s) into the returned chain along with the transformed func
            for converter in apply:
                func_src_user = _put_code_into_func_body(func_src_user, generated_chains_for_converters[converter])
            return (func_src_user, func)

    #none of the applies worked, so give up
    return (None, None)


def _try_gadget(name: str, all_gadgets: dict, seen: list):
    #terminate if provided
    if name in _set_config['provided']:
        return (f'#def {name}(*args, **kwargs): pass  #TODO provided\n\n', lambda: ...)  #any empty func would work

    for gadget, func in all_gadgets.items():
        if gadget in seen:
            continue

        if gadget.startswith(name):
            #print('trying', gadget)

            #func and this will be overwritten by the converters if needed
            func_src_user = _inspect.getsource(func)

            fullargspec = _inspect.getfullargspec(func)
            required_gadgets = fullargspec.kwonlyargs
            violations = _count_violations(func, required_gadgets)
            if violations:
                func_src_user, func = _try_convert(func_src_user, required_gadgets, violations, gadget, all_gadgets, seen)
                if not func:
                    continue
            else:
                #only when there was no violations is the function not rewritten and we have to manually remove kwonlyargs ourselves
                func_src_user = func_src_user.splitlines()
                if not violations:
                    func_src_user[0] = f'def {gadget}({", ".join(fullargspec.args)}):'   #replace the header to exclude gadget use
                func_src_user = '\n'.join(func_src_user) + '\n'


            #reaching this could mean theres no violations, or the violations are sorted out
            #XXX its unlikely that fullargspec.args changed after conversions if they were required, but just to be safe
            fullargspec = _inspect.getfullargspec(func)
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
                
                func_src_user = _put_code_into_func_body(func_src_user, next_src)
            
            if good:
                return (func_src_user, func)  #generated code so far, current gadget func
    
    return (None, None) #could be due to a gadget requiring an unknown gadget


#import near the end to avoid circular imports
from . import converters, utils, gadgets

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
        for path, _, filenames in _os.walk(gadgets_path):
            for f in filenames:
                if f.lower() == name + '.py':
                    gadget_type = _os.path.relpath(path, gadgets_path).split(_os.sep)[0]
                    break

        if gadget_type == None: raise NameError(f'gadget {name} not found!')
        
        #recursively obtain all gadgets of the same type
        all_gadgets = dict(_user_gadgets)  #add the user gadgets into the available gadgets list
        for path, _, filenames in _os.walk(gadgets_path + _os.sep + gadget_type):
            for f in filenames:
                filename, ext = _os.path.splitext(f)
                if ext.lower() == '.py':
                    #import the gadget file as a module
                    gadget_module = _importlib.import_module('.' + _os.path.relpath(path, gadgets_path).replace(_os.sep, '.') + '.' + filename, gadgets.__name__)
                    for attrname in dir(gadget_module):
                        if attrname.startswith(filename):
                            all_gadgets[attrname] = getattr(gadget_module, attrname)

        if gadget_type == 'python':  #returning just the string for python based chain is good
            chain, gadget_func = _try_gadget(name, all_gadgets, [])
            
            if not chain: return None

            params = _inspect.getfullargspec(gadget_func).args
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