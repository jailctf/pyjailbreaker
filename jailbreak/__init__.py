#avoid polluting the normal getattr space
import ast as _ast, os as _os, importlib as _importlib, inspect as _inspect, itertools as _itertools, asttokens as _asttokens
from types import FunctionType as _FunctionType

#
# Configuration interfaces
#

_registered_converters = {}  #mapping of converter function name -> list of types of data to apply to (e.g. specific AST nodes)
#TODO wildcard converters
_applicable_converters = {}  #violation type -> { violation node -> converter function }


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
#XXX currently implicitly assumes a violation type will be bound to a specific type of converter (e.g. PythonConverter for AST nodes)
#    but it might not be the case, e.g. the `platforms` field could be shared across bytecode and python ast
#    which means under this system AST converters could be used on bytecode, or vice versa
#TODO figure out some way to key this (either via directory mapping similar to gadgets, manual typing, or better implicit conversion)
#     current thought: reconciling gadget and converter structures seem better for parsing, but might be clunky for converters
#     since theres not that many for each type compared to gadgets
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

        _registered_converters[converter.__name__] = nodes
        return converter

    return apply

#
# End configuration interfaces
#

from . import converters, utils, gadgets, models


def _handle_whitelist(restrictions: set, checks: list):
    #in whitelist mode, if the type doesnt exist in checks, we assume it supports everything and thus there are no violations
    return set(restrictions).intersection(set(restrictions).difference(set(checks))) if checks else {}

def _handle_blacklist(restrictions: set, checks: list):
    #in blacklist mode, if the type doesnt exist in checks, we assume it supports nothing and thus all restrictions are violated
    return set(restrictions).intersection(set(checks)) if checks else set(restrictions)

def _manual_check(all_nodes: list, tokens: _asttokens.ASTTokens, exempt_tokens: set):
    #handle manual information
    checks = {}
    if _ast.get_docstring(tokens.tree.body[0]) != None:
        for line in _ast.get_docstring(tokens.tree.body[0]).strip().splitlines():
            field, val = line.strip().split(':', 1)
            checks[field.strip()] = _ast.literal_eval(val.strip())

#supported fields; field name -> matcher, parser
#e.g. restrictions are a, b and checks are b, c, d
#for whitelist: we return a since a is an requirement thats not satisfied
#for blacklist: we return b since b is banned
_restrictions_mapping = {
    #automatic fields
    'ast': (_handle_blacklist, lambda all_nodes, *_: {type(n) for n in all_nodes}),
    'char': (_handle_blacklist, lambda all_nodes, tokens, exempt_tokens: {c for n in all_nodes if hasattr(n, 'first_token') for tok in tokens.token_range(n.first_token, n.last_token) if tok not in exempt_tokens for c in tok.string}),
    'substr': (
        #requires a custom matcher and parser since we need the `res in check` part instead of a hash match that _handle_blacklist does with the set.intersection
        lambda restrictions, checks: {res for res, check in _itertools.product(restrictions, checks) if res in check} if checks else set(restrictions), 
        #''.join is needed to properly match (most, same line) substrings that span across multiple tokens, eg "()"
        lambda all_nodes, tokens, exempt_tokens: {''.join(tok.string for tok in tokens.token_range(n.first_token, n.last_token) if tok not in exempt_tokens) for n in all_nodes if hasattr(n, 'first_token')}
    ),
    #docstring fields
    'platforms': (_handle_whitelist, _manual_check),
    'versions': (_handle_whitelist, _manual_check),
}

def _count_violations_python(func_ast: _ast.Module, required_gadgets: 'list[_FunctionType]') -> dict:
    #add token info
    tokens = _asttokens.ASTTokens(_ast.unparse(func_ast), func_ast)

    all_nodes = []
    exempt_tokens = set()
    #need to actually traverse it instead of using ast.walk since we want to traverse only specific parts of an exempted node sometimes
    class Traverser(_ast.NodeVisitor):
        def generic_visit(self, node: _ast.AST):
            all_nodes.append(node)
            super().generic_visit(node)

        #do not include module nodes in all_nodes - this only exists once as the top level declaration
        def visit_Module(self, node: _ast.Module):
            super().generic_visit(node)

        def visit_FunctionDef(self, node: _ast.FunctionDef):
            #main gadget declaration, dont track
            if isinstance(node, _ast.FunctionDef) and node.name == func_ast.body[0].name:
                #also only visit the body and not any other parts of the function def
                for i, stmt in enumerate(node.body):
                    #skip docstring if it exists (ref: ast.get_docstring)
                    if isinstance(stmt, _ast.Expr) and isinstance(stmt.value, _ast.Constant) and isinstance(stmt.value.value, str): 
                        continue
                    super().visit(stmt)  #visit instead of generic_visit to select the right type of func
            else:
                all_nodes.append(node)  #otherwise still track
                super().generic_visit(node)

        def visit_Name(self, node: _ast.Name):
            nonlocal exempt_tokens
            #exempt tokens that references gadgets coz we can rewrite those
            if node.id in required_gadgets:
                exempt_tokens = exempt_tokens.union(tokens.token_range(node.first_token, node.last_token))
            super().generic_visit(node)

    Traverser().visit(tokens.tree)

    violations = {}
    for field, restrictions in _set_config['restrictions'].items():
        #apply the right handlers to the restriction type
        assert field in _restrictions_mapping, f"unsupported type {field}!"
        matcher, parser = _restrictions_mapping[field]

        type_violations = matcher(restrictions, parser(all_nodes, tokens, exempt_tokens))
        
        #print(func_ast.body[0].name, field, type_violations)

        #only track it if it has a violation
        if type_violations:
            violations[field] = type_violations

    return violations


_count_violations_mapping = {
    'python': _count_violations_python,
}

def _choose_converter_for_violation(type: str, violation, gadget: str, all_gadgets: 'dict[str, _FunctionType]', seen: 'list[str]', converter_class: 'type[models.ConverterBase]', gadget_type: str) -> 'models.ConverterBase | None':
    #choose first one that would succeed under our jail (there is no point in trying other converters if this one succeeds, assuming the kwargs annotations via @register_converter accurately depicts what the converter does)
    for converter_func in _applicable_converters[type][violation]:
        converter = converter_class(converter_func, applies=_registered_converters[converter_func.__name__])
        converter_required_gadgets = _inspect.getfullargspec(converter_func).kwonlyargs
        for next_gadget in converter_required_gadgets:
            gadget = _try_gadget(next_gadget, all_gadgets, seen + [gadget], gadget_type)
            if not gadget:
                continue  #not all dependencies can be resolved, next converter
            converter.add_dependency(gadget)  #we can add dependencies on the fly since if the converter is bad we throw it away anyway
        return converter
                
#if this returns true, the gadget wouldve been rewritten and the gadget will have tracked the converters, else nothing changed
def _try_convert(gadget: models.GadgetBase, required_gadgets: 'list[_FunctionType]', violations: dict, all_gadgets: 'dict[str, _FunctionType]', seen: 'list[str]', gadget_type: str) -> bool:
    #obtain a list of all converters that we should run to avoid the violations
    converter_class = models.converter_type_mapping[gadget_type]

    converters_to_run: 'set[models.ConverterBase]' = set()
    for type, type_violations in violations.items():
        if type not in _applicable_converters:   #no converters registered for the type
            return False
        
        for violation in type_violations:
            if violation in _applicable_converters[type] and _applicable_converters[type][violation]:
                converter = _choose_converter_for_violation(type, violation, gadget.name, all_gadgets, seen, converter_class, gadget_type)
                if not converter:
                    return False #we exhausted all the applicable converters for this violation, give up on this chain
                
                converters_to_run.add(converter)
            else:
                return False #not all violations can be converted away, give up on this chain

    #XXX dumb heuristic - try all converter application orders to see if any can actually achieve no violations
    #XXX situations where e.g. the strless converter uses chr(), which introduces CALLs and requires callless converter to run on it yet no CALLs were in the main gadget will just fail with this method
    #XXX but if we are lucky (eg main gadget has CALL violations so callless converter is in converters_to_run) then the conversion will pass
    for apply in _itertools.permutations(converters_to_run):
        #all converters in apply should be the same type, choose a random one to extract stuff and apply with
        new_data = gadget.extract()
        for converter in apply:
            new_data = converter.convert(new_data)
        #XXX we are assuming converters do not introduce new regressions, otherwise we will have to rerun the whole conversion test again when we see violations
        if not _count_violations_mapping[gadget_type](new_data, required_gadgets):
            #add the required gadget chain(s) into the returned chain along with the transformed func
            #only here is gadget modified
            gadget.apply_converters(apply, new_data)
            return True

    #none of the applies worked, so give up
    return False

#all_gadgets will be replaced with gadgets as we find them
def _try_gadget(name: str, all_gadgets: 'dict[str, _FunctionType | models.GadgetBase]', seen: 'list[str]', gadget_type: str):
    #terminate if provided

    #TODO cache this?
    gadget_class = models.gadget_type_mapping[gadget_type]
    #only python gadgets have inline
    if gadget_type == 'python' and _set_config['inline']:
        gadget_class = models.PythonGadgetInline


    if name in _set_config['provided']:
        return gadget_class.create_dummy_gadget(name)

    for gadget_name, func in all_gadgets.items():
        if gadget_name in seen:
            continue

        if gadget_name in _set_config['banned']:
            #gadget is user banned, ignore
            continue

        if gadget_name.startswith(name):
            #fast track: if we saw it and the gadget is memoized return early without computing again
            if isinstance(func, models.GadgetBase):
                #print('memoized', func)
                return func

            #print('trying', gadget)

            gadget = gadget_class(func)

            fullargspec = _inspect.getfullargspec(func)
            required_gadgets = fullargspec.kwonlyargs
            violations = _count_violations_mapping[gadget_type](gadget.extract(), required_gadgets)
            if violations:
                #if conversions cant be done, go to next candidate
                if not _try_convert(gadget, required_gadgets, violations, all_gadgets, seen, gadget_type):
                    continue

            #reaching this could mean theres no violations, or the violations are sorted out
        
            if not required_gadgets:   #no more to chain, return (base case)
                return gadget

            good = True
            for next_gadget in required_gadgets:
                new_gadget = _try_gadget(next_gadget, all_gadgets, seen + [gadget_name], gadget_type)

                #(at least) one of the required gadgets does not have a valid chain, drop out
                if not new_gadget:
                    good = False
                    break
                
                gadget.add_dependency(new_gadget)

            if good:
                #memoize the gadget for fast track return the next time we see it in another branch
                all_gadgets[gadget_name] = gadget
                return gadget
    
    return None #could be due to a gadget requiring an unknown gadget


del __path__  #prevent __getattr__ from running twice

#chain searcher, only runs if the name is not in scope
def __getattr__(name):
    if name == '__path__':
        raise AttributeError("path doesn't exist on the jailbreak module")
    
    try:
        #enable from jailbreak import * syntax
        if name == '__all__':
            return ['config', 'register_converter', 'register_user_gadget', 'converters', 'utils', 'gadgets', 'models']

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

        return _try_gadget(name, all_gadgets, [], gadget_type)
    except Exception as e:
        import traceback
        traceback.print_exc()