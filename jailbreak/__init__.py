#avoid polluting the normal getattr space
import ast as _ast, os as _os, importlib as _importlib, inspect as _inspect, itertools as _itertools
from types import FunctionType as _FunctionType

_registered_converters = {n: [] for a in _ast.AST.__subclasses__() for n in a.__subclasses__()} | {n: [] for n in _ast.AST.__subclasses__()}
_applicable_converters = {}

_set_config = {'restrictions': {}, 'provided': [], 'banned': [], 'inline': False}
_user_gadgets = {dirname: {} for dirname in next(_os.walk(__path__[0] + '/gadgets'))[1] if dirname != '__pycache__'}  #prepopulate gadget types from subdirs in gadgets

def config(**kwargs):
    global _set_config

    #put these in another field since they are not restrictions
    _set_config['provided'] = kwargs.pop('provided', [])
    _set_config['banned'] = kwargs.pop('banned', [])
    _set_config['inline'] = kwargs.pop('inline', False)

    _set_config['restrictions'] = kwargs


#for adding custom gadgets by the user
def register_user_gadget(func, gadget_type):
    if gadget_type in _user_gadgets:
        _user_gadgets[gadget_type][func.__name__] = func
    else:
        raise NameError(f"gadget type {gadget_type} does not exist!")


#for use as decorator on converters
def register_converter(*nodes, **violations):
    def apply(converter):
        for type, list in violations.items():
            type_violations = {} if type not in _applicable_converters else _applicable_converters[type]

            for violation in list:
                if violation in type_violations:
                    type_violations[violation].append(converter)
                else:
                    type_violations[violation] = [converter]

            _applicable_converters[type] = type_violations

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

#attr decides which block of statements in func_ast we are currently operating on
def _convert_return_to_assign(func_ast, name, attr='body'):
    #there might be arbitrary depth module containers, so use a transformer here too
    #NOTE even though this function supports arbitrary depth rewrites its not recommended to have module containers since it might have side effects as theyre passed by reference
    #NOTE e.g. when Inliner uses the same gadget_ast.body for calling this, even though the list is different after shallow copy if there are Module nodes then they will be the same reference and thus rewriting one return will show up in another
    visited = False
    class ReturnToAssign(_ast.NodeTransformer):
        def visit_Return(self, node: _ast.Return):
            nonlocal visited
            visited = True
            return _ast.fix_missing_locations(_ast.Assign([_ast.Name(name)], node.value))
    func_ast = ReturnToAssign().visit(func_ast)

    if not visited:
        #no returns, add a none so the name at least resolves
        getattr(func_ast, attr).append(_ast.Assign([_ast.Name(name)], _ast.Name('None')))
    return _ast.fix_missing_locations(func_ast)

#convert all calls into inlined code
#ast walker for applying given converters
#TODO check if theres ever any case where the dependent gadgets are not immediately used (i dont think so?)
class Inliner(_ast.NodeTransformer):
    def __init__(self, gadget_name: str, gadget_ast: _ast.FunctionDef) -> None:
        super().__init__()
        self.gadget_name = gadget_name

        #rewrite all references inside gadget_ast to be unique
        #TODO check how this deals with clashing names due to scoping (e.g. same name inside a nested function)
        param_names = [a.arg for a in gadget_ast.args.args]

        class NameRewrite(_ast.NodeTransformer):
            def visit_Name(self, node: _ast.Name):
                if node.id in param_names:
                    node.id = f'{gadget_name}_{node.id}'
                return super().generic_visit(node)
            
        self.gadget_ast = NameRewrite().visit(gadget_ast)


    #XXX i think this breaks if walrus operators or any name assignment is done and is used by the calls as a param *inside* the same statement
    """
    e.g. in the following scenario:

    def gadget_call(a):
        print(a)
    [a:=1, gadget_call(a)]

    since the rewrite would try to make it so that it becomes

    gadget_call_0 = print(a)
    [a:=1, gadget_call_0]
    """
    #TODO a better way to do this would be to figure out a statement -> expression converter and use it here instead of precomputing (but stmt -> expr is not always possible so)
    #alternatively document this and avoid creating gadgets with too many expression quirks (common cases like `[gadget_call(a) for a in list]` still exists though, but is definitely rewritable to avoid hitting this)
    def generic_visit(self, node: _ast.AST):
        def get_stmt_body_attrs(node):
            return [attr for attr, data in vars(node).items() if isinstance(data, list) and len(data) > 0 and isinstance(data[0], _ast.stmt)]

        #on every node entry (that has a body of statements), figure out all the calls IMMEDIATE TO THAT BODY OF STATEMENTS to tracked gadgets and precompute it before the statement
        #so to ensure the scoping is at the correct level
        #NOTE body of statements can be any of [body, orelse, finalbody] (so far <= 3.13) but just to be flexible make it dynamic (only continue if a list of statements is found)
        stmt_body_attrs = get_stmt_body_attrs(node)
        if stmt_body_attrs:
            gadget_name = self.gadget_name

            #nullify the function def if its tracked since it will be inlined
            if isinstance(node, _ast.FunctionDef):
                if node.name == gadget_name:
                    return _ast.Module([], [])

            #obtain the calls (and rewrite it so that its referencing the precomputed variable instead) first
            for attr in stmt_body_attrs:
                calls = {}
                class CallRewrite(_ast.NodeTransformer):
                    def generic_visit(self, node: _ast.AST) -> _ast.AST:
                        stmt_body_attrs = get_stmt_body_attrs(node)
                        if stmt_body_attrs:
                            #do NOT traverse deeper on body of statements, let the main Inliner visit it instead - but we still need to traverse non body statements
                            #dynamically traverse all other expressions that are not body of statements, e.g. target / iter in for loops
                            #NOTE each name in the grammar has a class that extends ast.AST, even if there isnt a proper node class for it (e.g. comprehension)
                            #NOTE so the only thing we need to handle is the optional case (which is None on not exist) and the list case (which is a list of classes that extends ast.AST)
                            for attr in set(dir(node)).difference(stmt_body_attrs):
                                data = getattr(node, attr)
                                if isinstance(data, list):
                                    for i, element in enumerate(data):
                                        if isinstance(data, _ast.AST):  #in theory if one element is a statement all should be
                                            data[i] = self.generic_visit(element)
                                elif isinstance(data, _ast.AST):
                                    setattr(node, attr, self.generic_visit(data))

                            return node
                        return super().generic_visit(node)

                    def visit_Call(self, node: _ast.Call):
                        nonlocal gadget_name, calls
                        if isinstance(node.func, _ast.Name) and gadget_name.startswith(node.func.id):
                            if node.func.id in calls:
                                calls[node.func.id].append(node)
                            else:
                                calls[node.func.id] = [node]
                            #use index as unique id
                            node = _ast.fix_missing_locations(_ast.Name(f'{gadget_name}_{len(calls[node.func.id]) - 1}'))
                        return super().generic_visit(node)
                orig_code = [CallRewrite().visit(stmt) for stmt in getattr(node, attr)]

                setattr(node, attr, [])   #clear out the original code, its rewritten in orig_code
                #precompute the calls before the statement actually runs
                for gadget, nodes in calls.items():
                    for i, n in enumerate(nodes):
                        #rename references in the gadget code
                        #XXX this assumes the call arg count is correct in the gadgets
                        for j, arg in enumerate(n.args):
                            internal_param_name = self.gadget_ast.args.args[j].arg
                            #see NameRewrite above
                            getattr(node, attr).append(_ast.Assign([_ast.Name(f'{gadget_name}_{internal_param_name}')], arg))
                        #add the gadget code to run (after visitinge each node first)
                        getattr(node, attr).extend(self.gadget_ast.body)
                        #assign the result
                        node = _convert_return_to_assign(node, f'{gadget_name}_{i}', attr)

                getattr(node, attr).extend(orig_code)

            node = _ast.fix_missing_locations(node)
        
        #otherwise return itself
        return super().generic_visit(node)


#required since there could be variable naming clashes that break a gadget if its not nested
def _put_code_into_func_body(func_ast: _ast.Module, code_ast: _ast.Module):
    #only try inliner if the gadget we depend on requires arguments
    if _set_config['inline'] and isinstance(code_ast.body[0], _ast.FunctionDef) and code_ast.body[0].args:
        # print(f'given\n{_ast.unparse(code_ast.body[0])}')
        # print(f'orig\n{_ast.unparse(func_ast)}')
        func_ast = Inliner(code_ast.body[0].name, code_ast.body[0]).visit(func_ast)
        # print(f'rewritten\n{_ast.unparse(func_ast)}\n\n')
    else:            
        #add to the front of the func def, also to preserve the body[0] == FunctionDef assumption
        if isinstance(func_ast.body[0], _ast.FunctionDef):
            func_ast.body[0].body = code_ast.body + func_ast.body[0].body
        else:
            func_ast.body = code_ast.body + func_ast.body  #inlined, just add to the front
    return _ast.fix_missing_locations(func_ast)


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
         
#fields that works as a whitelist instead of a blacklist in violations
_whitelist_fields = ['platforms', 'versions']

def _count_violations(func_ast: _ast.Module, required_gadgets) -> dict:
    #add token info
    import asttokens
    tokens = asttokens.ASTTokens(_ast.unparse(func_ast), func_ast)

    all_nodes = [n for n in _ast.walk(tokens.tree) if not _exempt_node(n, required_gadgets, func_ast.body[0].name)]
    
    #handle manual information
    checks = {}
    if _ast.get_docstring(func_ast.body[0]) != None:
        for line in _ast.get_docstring(func_ast.body[0]).strip().splitlines():
            field, val = line.strip().split(':', 1)
            checks[field.strip()] = _ast.literal_eval(val.strip())

    #handle automatic information
    checks['ast'] = {type(n) for n in all_nodes}
    checks['char'] = {c for n in all_nodes if hasattr(n, 'first_token') for tok in tokens.token_range(n.first_token, n.last_token) for c in tok.string}
    #TODO also make a substring check instead of just char

    violations = {}
    for field, restrictions in _set_config['restrictions'].items():
        #e.g. restrictions are a, b and checks are b, c, d
        #for whitelist: we return a since a is an requirement thats not satisfied
        #for blacklist: we return b since b is banned

        if field in _whitelist_fields:
            #in whitelist mode, if the type doesnt exist in checks, we assume it supports everything and thus there are no violations
            type_violations = set(restrictions).intersection(set(restrictions).difference(set(checks[field]))) if field in checks else {}
        else:
            #in blacklist mode, if the type doesnt exist in checks, we assume it supports nothing and thus all restrictions are violated
            type_violations = set(restrictions).intersection(set(checks[field])) if field in checks else set(restrictions)

        #only track it if it has a violation
        if type_violations:
            violations[field] = type_violations

    return violations

def _choose_converter_for_violation(type, violation, gadget: str, all_gadgets: dict, seen: list):
    #choose first one that would succeed under our jail (there is no point in trying other converters if this one succeeds, assuming the kwargs annotations via @register_converter accurately depicts what the converter does)
    for converter in _applicable_converters[type][violation]:
        converter_required_gadgets = _inspect.getfullargspec(converter).kwonlyargs
        for next_gadget in converter_required_gadgets:
            chain, _ = _try_gadget(next_gadget, all_gadgets, seen + [gadget])
            if chain:
                return (converter, chain)
                
def _try_convert(func_ast: _ast.Module, required_gadgets: list, violations: dict, gadget: str, all_gadgets: dict, seen: list):
    #obtain a list of all converters that we should run to avoid the violations
    converters_to_run = set()
    generated_chains_for_converters = {}
    for type, type_violations in violations.items():
        if type not in _applicable_converters:   #no converters registered for the type
            return (None, None)
        
        for violation in type_violations:
            if violation in _applicable_converters[type] and _applicable_converters[type][violation]:
                converter, chain = _choose_converter_for_violation(type, violation, gadget, all_gadgets, seen)
                generated_chains_for_converters[converter] = chain
                converters_to_run.add(converter)
            else:
                return (None, None)  #not all violations can be converted away, give up on this chain

    #XXX dumb heuristic - try all converter application orders to see if any can actually achieve no violations
    #XXX situations where e.g. the strless converter uses chr(), which introduces CALLs and requires callless converter to run on it yet no CALLs were in the main gadget will just fail with this method
    #XXX but if we are lucky (eg main gadget has CALL violations so callless converter is in converters_to_run) then the conversion will pass
    for apply in _itertools.permutations(converters_to_run):
        new_ast = func_ast
        #remove kwonlyargs from the function def coz its not actually part of the function
        new_ast.body[0].args.kwonlyargs = []
        new_ast.body[0].args.kw_defaults = []  #must match kwonlyargs
        for converter in apply:
            new_ast = ApplyConverter(converter).visit(new_ast)
        new_func = _FunctionType(compile(new_ast, '<string>', 'exec').co_consts[0], globals())
        #TODO figure out if docstrings are preserved after rewrite, since count violations require it (if it does we need to remove it at the end)
        #XXX we are assuming converters do not introduce new regressions, otherwise we will have to rerun the whole conversion test again when we see violations
        if not _count_violations(new_ast, required_gadgets):
            #add the required gadget chain(s) into the returned chain along with the transformed func
            for converter in apply:
                new_ast = _put_code_into_func_body(new_ast, generated_chains_for_converters[converter])
            return (new_ast, new_func)

    #none of the applies worked, so give up
    return (None, None)


def _try_gadget(name: str, all_gadgets: dict, seen: list):
    #terminate if provided
    if name in _set_config['provided']:
        #NOTE ast trees dont have a node for comments, but we can abuse Name nodes since there are no validity checking
        #NOTE need to wrap in Expr so its in a new line
        return (_ast.Module([_ast.Expr(_ast.Name(f'#def {name}(*args, **kwargs): pass  #TODO provided'))]), lambda: ...)  #any empty func would work

    for gadget, func in all_gadgets.items():
        if gadget in seen:
            continue

        if gadget in _set_config['banned']:
            #gadget is user banned, ignore
            continue

        if gadget.startswith(name):
            #print('trying', gadget)

            #func and this will be overwritten by the converters if needed
            func_ast = _ast.parse(_inspect.getsource(func))

            fullargspec = _inspect.getfullargspec(func)
            required_gadgets = fullargspec.kwonlyargs
            violations = _count_violations(func_ast, required_gadgets)
            if violations:
                func_ast, func = _try_convert(func_ast, required_gadgets, violations, gadget, all_gadgets, seen)
                if not func:
                    continue
            else:
                #only when there was no violations is the function not rewritten and we have to manually remove kwonlyargs ourselves
                func_ast.body[0].args.kwonlyargs = []
                func_ast.body[0].args.kw_defaults = []  #must match kwonlyargs


            #reaching this could mean theres no violations, or the violations are sorted out
            #XXX its unlikely that fullargspec.args changed after conversions if they were required, but just to be safe
            fullargspec = _inspect.getfullargspec(func)
            if _set_config['inline']:
                #easy case, can just put directly run the function code at the top and assign it to a variable since its not dependent on parameters
                if not fullargspec.args:  
                    func_ast.body = func_ast.body[0].body
                    func_ast = _convert_return_to_assign(func_ast, name)
                #otherwise we wait until _put_code_into_func_body runs in each gadget that depends on this gadget, which Inliner will rewrite references on each call
            else:
                #simply tell the user we are using this specific gadget for the gadget they want by assigning it
                func_ast.body.append(_ast.Assign([_ast.Name(name)], _ast.Name(gadget) if fullargspec.args else _ast.Call(_ast.Name(gadget), [], [])))
                func_ast = _ast.fix_missing_locations(func_ast)

        
            if not required_gadgets:   #no more to chain, return (base case)
                return (func_ast, func)

            good = True
            for next_gadget in required_gadgets:
                next_ast, _ = _try_gadget(next_gadget, all_gadgets, seen + [gadget])

                #(at least) one of the required gadgets does not have a valid chain, drop out
                if not next_ast:
                    good = False
                    break
                
                func_ast = _put_code_into_func_body(func_ast, next_ast)

            if good:
                return (func_ast, func)  #generated code so far, current gadget func
    
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
            return ['config', 'register_converter', 'register_user_gadget', 'converters', 'utils', 'gadgets']

        gadgets_path = gadgets.__path__[0]

        gadget_type = None
        #check user gadgets first
        for gt, user_gadgets in _user_gadgets.items():
            if name in [n.split('__')[0] for n in user_gadgets]:
                gadget_type = gt

        if not gadget_type:
            #check repo gadgets
            for path, _, filenames in _os.walk(gadgets_path):
                for f in filenames:
                    if f.lower() == name + '.py':
                        gadget_type = _os.path.relpath(path, gadgets_path).split(_os.sep)[0]
                        break

        if gadget_type == None: raise NameError(f'gadget {name} not found!')
        
        #recursively obtain all gadgets of the same type
        all_gadgets = dict(_user_gadgets[gadget_type])  #add the user gadgets into the available gadgets list
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
                chain_src = _ast.unparse(chain) + '\n'
                chain_src += f'{name}'
                if params: 
                    chain_src += f'({", ".join(args)})'
                    
                if _set_config['inline'] and isinstance(chain.body[0], _ast.FunctionDef):
                    #try one last inlining with the user given params
                    return _ast.unparse(Inliner(chain.body[0].name, chain.body[0]).visit(_ast.parse(chain_src))) + '\n'
                else:
                    return chain_src + '\n'

            return param_wrapper
        else:
            return exec(chain) #apply restrictions and obtain bytes; works fairly differently from python gadget chains
    except Exception as e:
        import traceback
        traceback.print_exc()