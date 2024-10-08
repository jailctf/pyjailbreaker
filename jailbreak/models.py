"""
This file contains the specification classes for generating a payload chain of the respective type,
given the gadget function and its respective dependencies and/or conversions done to it.

They form the core of the payload generator, with the following goals in mind:
 - Static specification using the models should be easy for manually writing payload chains, and should generate workable payloads
 - Should preserve compatility with on-the-fly chain generations e.g. via dependency traversal (the current mechanism of the payload generator)
 - Should be abstract enough that all types of pyjail payloads (e.g. python, pickle, bytecode) can be specified by mostly the same mechanism and be compatible with the payload generator
 - Should be reusable, i.e. the same gadget instance can exist in multiple paths (e.g. for optimization via memoization)
 - Should track possible paths even if they are incomplete, e.g. with missing gadgets or has violations (TODO)
   - Should suggest paths based on heuristics such as least amount of violations / most gadgets in chain (TODO)

To make a new gadget type, perfrom the following:
 - extend ConverterBase and GadgetBase, add required data and implement the respective functions
 - add the new converter class and gadget class to the respective type_mapping
 - in [`__init__.py`](jailbreak/__init__.py), create a new `_count_violations` function for the type that checks for violation type that applies to the gadget type and add it to `_count_violations_mapping`

NOTE: The models do not perform any checks on whether the generated code conforms to restrictions nor whether it works -
      it is assumed that given chain specification is correct.
"""

from dataclasses import dataclass as _dataclass, field as _field
from types import FunctionType as _FunctionType
import ast as _ast, inspect as _inspect, copy as _copy, os as _os, importlib as _importlib

#
# Configuration interfaces
#

registered_converters = {}  #mapping of converter function -> list of types of data to apply to (e.g. specific AST nodes)
#TODO wildcard converters
applicable_converters = {}  #violation type -> { violation node -> converter function }


set_config = {'restrictions': {}, 'provided': [], 'banned': [], 'inline': False}

def config(**kwargs):
    global set_config

    #put these in another field since they are not restrictions
    set_config['provided'] = kwargs.pop('provided', [])
    set_config['banned'] = kwargs.pop('banned', [])
    set_config['inline'] = kwargs.pop('inline', False)

    set_config['restrictions'] = kwargs


#for adding custom gadgets by the user
def register_user_gadget(func, gadget_type):
    if gadget_type in all_gadgets:
        all_gadgets[gadget_type][func.__name__] = func
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
            type_violations = {} if type not in applicable_converters else applicable_converters[type]

            for violation in list:
                if violation in type_violations:
                    type_violations[violation].append(converter)
                else:
                    type_violations[violation] = [converter]

            applicable_converters[type] = type_violations

        registered_converters[converter] = nodes
        return converter

    return apply

#
# End configuration interfaces
#



#
# Utility functions/classes
#

#XXX have to define these here so we can actually import it

#get all repo gadgets by traversing the repo
def get_all_gadgets_in_repo() -> 'dict[str, dict[str, _FunctionType]]':
    from . import gadgets
    gadgets_path = gadgets.__path__[0]

    all_gadgets = {}
    for gadget_type in next(_os.walk(gadgets_path))[1]:
        #non gadget dirs
        if gadget_type in ['__pycache__']:
            continue

        all_gadgets[gadget_type] = {}

        #recursively obtain all gadgets of the same type
        for path, _, filenames in _os.walk(gadgets_path + _os.sep + gadget_type):
            for f in filenames:
                filename, ext = _os.path.splitext(f)
                if ext.lower() == '.py':
                    #import the gadget file as a module
                    gadget_module = _importlib.import_module('.' + _os.path.relpath(path, gadgets_path).replace(_os.sep, '.') + '.' + filename, gadgets.__name__)
                    for attrname in dir(gadget_module):
                        if attrname.startswith(filename):  #XXX more accurately it should start with <filename>__, but it should be fine
                            all_gadgets[gadget_type][attrname] = getattr(gadget_module, attrname)

    return all_gadgets

#XXX this doesnt update if any new gadgets show up until you reload the module but i dont think ppl would do that
all_gadgets = get_all_gadgets_in_repo()   #cache the gadgets for use



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



#ast walker for applying given converters
class ApplyConverter(_ast.NodeTransformer):
    def __init__(self, converter: _FunctionType, applies: list) -> None:
        super().__init__()
        self.applies = applies
        #change the converter so that the gadgets in kwonlyargs are not required to call the func
        self.converter = _FunctionType(converter.__code__.replace(co_kwonlyargcount=0), converter.__globals__)

        #for giving a full node path from top level to current node into converters, for checking conditions like "do not convert format_spec constants into calls"
        self.curr_path = [] 

    def visit(self, node: _ast.AST) -> _ast.AST:
        #track the node
        self.curr_path.append(node)

        #actually visit the node
        ret = super().visit(node)

        #remove the node from path now that we are done with it; last item should be itself
        assert node == self.curr_path.pop()
        return ret

    def generic_visit(self, node: _ast.AST) -> _ast.AST:
        if type(node) in self.applies:
            node = _ast.fix_missing_locations(self.converter(self.curr_path))
        
        #otherwise return itself
        return super().generic_visit(node)


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

    #nested functions inside a gadget that accesses the gadget's variable will use nonlocal, but once we inline it it will be a global var ref
    def visit_Nonlocal(self, node: _ast.Nonlocal):
        new_node = _ast.Global(node.names)
        return super().generic_visit(_ast.copy_location(new_node, node))

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
            if not hasattr(node, '__dict__'):
                breakpoint()
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
                            for attr in set(dir(node)).difference(stmt_body_attrs):  #XXX could just use _fields for less iterations, see ast.py generic_visit
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


#
# End utility functions/classes
#


#common base for both converters and gadgets
@_dataclass(eq=False)
class ModelBase:
    #a gadget should either have a func passed to it, or a name that it would infer the func from
    #NOTE: func should not change even if it is rewritten
    func: _FunctionType = _field(default=None, repr=False)  #no useful info to repr here, hide it
    name: str = _field(default=None)

    #all dependencies of a gadget of subclass should have dependencies of also the same subclass
    dependencies: 'list[GadgetBase]' = _field(default_factory=list)
    dummy: bool = _field(default=False)

    #TODO some mechanism to track failed gadget chains for giving partial suggestions

    #convert the gadget into a dummy gadget - child classes should override it to provide dummy data for their respective types
    def _make_dummy(self):
        def dummy(): pass
        self.func = dummy
        #name is already set

    #NOTE child classes should check if its a dummy before adding their own data
    def __post_init__(self):
        if self.dummy:
            self._make_dummy()
            return

        #populate both func or name given either one of them
        assert self.func or self.name, "must provide either func or name!"
        if self.func: 
            self.name = self.func.__name__
        else:
            #gadgets and converters have different ways of looking this up
            self.func = self._lookup_name(self.name)
            assert self.func, f'{self.name} not found ({type(self)})!'

    #NOTE LEAF child classes should run this at the end of their __post_init__
    #     aka this should be run last in __post_init__
    def _transform_data(self):
        #run add_dependency on all dependencies
        #NOTE this has to be done for every data field that has a setter if child classes have them
        #     e.g. converters -> apply_converters
        dependencies = self.dependencies
        self.dependencies = []
        for dep in dependencies:
            self.add_dependency(dep)

    def _lookup_name(self, name):
        assert False, 'not implemented'

    def add_dependency(self, dependency):
        self.dependencies.append(dependency)

    def __hash__(self):
        return self.name.__hash__()


#documents a gadget
@_dataclass(eq=False)
class GadgetBase(ModelBase):
    #gadgets have converters
    converters: 'list[ConverterBase]' = _field(default_factory=list)

    #user facing interface, must implement for all gadgets
    def __call__(self, *args, **kwargs):
        assert False, "gadget call not implemented"

    def _transform_data(self):
        #run apply_converters on the uninitialized converters
        converters = self.converters
        self.converters = []
        self.apply_converters(converters)
        #before deps
        super()._transform_data()


    def _lookup_name(self, name):        
        #get type name from the gadget's own type, traversing the mro if needed
        keys, values = list(gadget_type_mapping.keys()), list(gadget_type_mapping.values())
        for cls in type(self).mro():
            if cls in values:
                gadget_type = keys[values.index(cls)]

        #fetch func from _all_gadgets
        if name in all_gadgets[gadget_type]:
            return all_gadgets[gadget_type][name]
        
        return None

    #NOTE: child classes should extend these for converters to use the raw data properly

    #extract data for converters
    #NOTE: should make a COPY since the data could be discarded
    def extract(self):
        return None

    #apply the converters, along with raw data that weve converted (or generate the data if none is provided)
    #NOTE: returns data for child classes to apply it to the right field
    #NOTE: ALL converters in this list should be the same type
    def apply_converters(self, converters: 'list[ConverterBase]', data = None):
        if not data:
            data = self.extract()
            for converter in converters:
                data = converter.convert(data, self)
        self.converters += converters
        return data


#documents an converter
@_dataclass(eq=False)
class ConverterBase(ModelBase):
    #what data this converter applies to
    applies: list = _field(init=False, repr=False)

    #we must make applies default due to how dataclasses work, so assert here just to make sure
    def __post_init__(self):
        super().__post_init__()

        #XXX for now we dont support dummy converters - no idea how that would be useful but it might be in the future
        assert not self.dummy, "dummy converters not supported"
        
        #XXX this introduces more dependencies on global namespace but whatever finding gadget given anme also uses that
        self.applies = registered_converters[self.func]

        #NOTE remember to run _transform_data if there are data to transform

    def _lookup_name(self, name):        
        #fetch func from registered_converters
        for func in registered_converters:
            if func.__name__ == name:
                return func
        
        return None

    #attempts to convert some raw data using this converter
    #gadget is passed in so any necessary pre/post processing specific to the gadget type could be done
    #NOTE: raw, COPIED data since we dont want to change the gadget itself at this stage,
    #      we are just testing and the data could be discarded
    def convert(self, data, gadget: 'GadgetBase'):
        pass



#documents a python converter
@_dataclass(eq=False)
class PythonConverter(ConverterBase):
    def convert(self, data: _ast.AST, gadget: 'PythonGadget'):
        #clean docstrings off data first to avoid unnecessary conversions / false positives (since the docstrings will no longer match the one in orig_ast)
        gadget.remove_docstring(data)
        return ApplyConverter(self.func, self.applies).visit(data)


#documents a python gadget
@_dataclass(eq=False)
class PythonGadget(GadgetBase):
    #ast funcs is generated automatically and has no useful info (no repr), ignore
    #original gadget ast, will never change
    orig_ast: _ast.AST = _field(init=False, repr=False) 
    #gadget ast, could be converted via apply_converters
    #NOTE for inlined gadgets func_ast == chain_ast, since inliner directly modifies func_ast for chaining
    func_ast: _ast.AST = _field(init=False, repr=False)
    #dependency chain ast, to be merged in at the end
    chain_ast: _ast.AST = _field(init=False, repr=False)
    #setting this field should be done by specifying the class instead, hence init=False and repr=False
    inline: bool = _field(init=False, repr=False, default=False)

    #create a dummy gadget that returns a commented out func def
    def _make_dummy(self):
        super()._make_dummy()
        #NOTE ast trees dont have a node for comments, but we can abuse Name nodes since there are no validity checking
        #NOTE need to wrap in Expr so its in a new line
        self.func_ast = _ast.Module([_ast.Expr(_ast.Name(f'#def {self.name}(*args, **kwargs): pass  #TODO provided'))], [])
        self.chain_ast = _ast.Module([], []) if not self.inline else self.func_ast
        self.orig_ast = _copy.deepcopy(self.func_ast)


    #override: also initialize func_ast for this gadget
    def __post_init__(self):
        super().__post_init__()
        if not self.dummy:
            self.func_ast = _ast.parse(_inspect.getsource(self.func).strip())  #strip to accomodate for nested function sources (e.g. the one at create_dummy_gadget)
            self.orig_ast = _copy.deepcopy(self.func_ast)
            self.chain_ast = _ast.Module([], []) if not self.inline else self.func_ast #empty container if not inline else same ref as func_ast coz the chain directly modifies the func_ast

            self._transform_data()

    #this should run when we are prepping the raw gadget for chaining - it would add the required assigns/renaming for the gadget to be used by other gadgets
    def _ready_gadget_for_use(self, ast: _ast.Module) -> _ast.Module:        
        #before this runs, it should be a single func
        assert len(ast.body) == 1 and isinstance(ast.body[0], _ast.FunctionDef), 'gadget ast is not a pure top level function!'

        #avoid modifying the top level gadget, make a shallow copy
        ast = _ast.Module(list(ast.body), [])
        gadget_name, name = self._get_gadget_names_from_ast(ast)
        if self.inline:
            #only run in simple case (no args), otherwise inliner shouldve handled it in either _put_code_into_func_body or the final __call__
            if not ast.body[0].args.args:
                ast = _convert_return_to_assign(ast, name)
        else:
            #if we are putting a function code definition into the body, tell the user we are using this specific gadget for the gadget they want by assigning it
            ast.body.append(_ast.fix_missing_locations(_ast.Assign([_ast.Name(name)], _ast.Name(gadget_name) if ast.body[0].args.args else _ast.Call(_ast.Name(gadget_name), [], []))))
        return ast
    
    def _get_gadget_names_from_ast(self, ast: _ast.Module):
        gadget_name = ast.body[0].name
        name = gadget_name.split('__')[0]
        return gadget_name, name

    #puts code (either a chain of gadgets or just one gadget) into a gadget's function body
    #NOTE: func_ast is modifiable, but code_ast should be read only
    def _put_code_into_func_body(self, func_ast: _ast.Module, code_ast: _ast.Module) -> _ast.Module:
        #nothing to do, skip
        if not len(code_ast.body):
            return func_ast

        code_ast_is_func = len(code_ast.body) == 1 and isinstance(code_ast.body[0], _ast.FunctionDef)
        func_ast_is_func = len(func_ast.body) == 1 and isinstance(func_ast.body[0], _ast.FunctionDef)

        #only try inliner if the gadget we depend on requires arguments, otherwise its the same method as non inlined, just we grab the function body instead of the whole function def
        if self.inline and code_ast_is_func and code_ast.body[0].args.args:
            #print(f'given\n{_ast.unparse(code_ast.body[0])}')
            #print(f'orig\n{_ast.unparse(func_ast)}')
            func_ast = Inliner(code_ast.body[0].name, code_ast.body[0]).visit(func_ast)
            #print(f'rewritten\n{_ast.unparse(func_ast)}\n\n')
        else:
            body = code_ast.body
            if code_ast_is_func:
                code_ast = self._ready_gadget_for_use(code_ast)
                #recopy body since code_ast is remade; if its the simple inline case we copy the body of the chain only
                body = code_ast.body[0].body if self.inline and not code_ast.body[0].args.args else code_ast.body

            #add to the front of the func def, also to preserve the body[0] == FunctionDef assumption
            #required since there could be variable naming clashes that break a gadget if the code is not nested inside the func def
            if func_ast.body and func_ast_is_func:
                func_ast.body[0].body = body + func_ast.body[0].body
            else:
                func_ast.body = body + func_ast.body  #inlined, just add to the front

            
        return _ast.fix_missing_locations(func_ast)

    #NOTE: modifies ast
    def remove_docstring(self, ast):
        #remove gadget docstrings if any (ref: ast.get_docstring)
        #body of the functiondef, should at least have one element or else its an invalid function anyway
        first_func_body_node = self.orig_ast.body[0].body[0]  #NOTE: use orig_ast since func_ast couldve been modified by this time
        if isinstance(first_func_body_node, _ast.Expr) and isinstance(first_func_body_node.value, _ast.Constant) and isinstance(first_func_body_node.value.value, str): 
            #find the equivalent docstring in ast and remove it
            for stmt in ast.body[0].body:
                if isinstance(stmt, _ast.Expr) and isinstance(stmt.value, _ast.Constant) and isinstance(stmt.value.value, str) and stmt.value.value == first_func_body_node.value.value:
                    ast.body[0].body.remove(stmt)
                    break

    #merges the func ast and the chain ast together
    #this also removes some gadget metadata thats for internal use, so is functionally similar to _ready_gadget_for_use, except this gives a raw function gadget
    def get_full_ast(self) -> _ast.Module:
        #make a new ast node to stuff into; this shouldnt take too long since func_ast is small (just the gadget) while chain_ast could be big (the whole chain)
        #XXX deepcopy is slow even on func_ast for inline = True since func_ast == chain_ast
        full_ast = _copy.deepcopy(self.func_ast)

        #could be Expr for dummy gadgets
        if isinstance(full_ast.body[0], _ast.FunctionDef):
            #XXX its more efficient to do it right when the gadget is registered, but this could screw with the traversal checks that relies on kwargs and docstrings
            #    we could redirect all of those checks to orig_ast instead, but not sure how worth it is to optimize it like this

            #remove kwonlyargs from the function def coz its not actually part of the function
            full_ast.body[0].args.kwonlyargs = []
            full_ast.body[0].args.kw_defaults = []  #must match kwonlyargs

            self.remove_docstring(full_ast)

        #if we are inlining func_ast == chain_ast anyways due to how the chain modifies func_ast directly so dont put code in
        if not self.inline:
            self._put_code_into_func_body(full_ast, self.chain_ast)
        return full_ast
        

    #terminator call (i.e. the user facing part), get the whole src of the gadget
    def __call__(self, *args):
        if self.dummy:  #no need to process much, just grab the ast
            return _ast.unparse(self.func_ast) + '\n'

        params = _inspect.getfullargspec(self.func).args
        _, name = self._get_gadget_names_from_ast(self.func_ast)
        #use _put_code_into_func_body instead of _ready_gadget_for_use here since the former also does simple inlining cases
        full_ast = self.get_full_ast()

        #for complex inline cases, we need to add a reference before we put code into func body and trigger inliner so the code is generated correctly
        #without a reference, inliner will assume the function is never used and return an empty gadget
        if params and self.inline:
            #if there are params, add the user data into it and grab the ast back for putting code into func body
            chain_src = _ast.unparse(full_ast) + f'\n{name}({", ".join(args)})'
            full_ast = _ast.parse(chain_src)

        #_put_code_into_func_body deals with cleaning up the function via _ready_gadget_for_use, and handles both simple and complex inlining cases if needed
        src = _ast.unparse(self._put_code_into_func_body(_ast.Module([], []), full_ast))

        #for non inline cases only (simple inline cases does not have params), we can add it to the src directly after
        if params and not self.inline:
            src += f'\n{name}({", ".join(args)})'
        
        return src + '\n'

    
    #override: also put code into our func_ast
    def add_dependency(self, dependency: 'PythonGadget'):
        super().add_dependency(dependency)
        self._put_code_into_func_body(self.chain_ast, dependency.get_full_ast())
    
    #override: extract func_ast for python gadgets
    def extract(self):
        return _copy.deepcopy(self.func_ast)

    #override: basically same thing as add_dependency, but we directly put code from the converter dependencies into ours
    def apply_converters(self, converters: 'list[ConverterBase]', data: _ast.AST = None):
        #replace func_ast with the new data we computed
        self.func_ast = super().apply_converters(converters, data)

        if self.inline:
            self.chain_ast = self.func_ast  #also need to update chain_ast's reference to use the new one
        for converter in converters:
            for dep in converter.dependencies:
                #assume the dependencies are of the same effective class - its hard to check if theyre subclasses of each other
                #the chain is basically cached already in dep.chain_ast, no need to worry about performance
                self._put_code_into_func_body(self.chain_ast, dep.get_full_ast())

        #for chaining if needed (very unlikely this will have child classes but for consistency since base class also returns data)
        return self.func_ast


#convenience class for creating inline python gadgets without declaring it every time
@_dataclass(eq=False)
class PythonGadgetInline(PythonGadget):
    inline: bool = _field(init=False, repr=False, default=True)
    #override: force inline = True
    def __post_init__(self):
        self.inline = True
        #post init does things based on inline value, so put it later
        super().__post_init__()



#mappings for traverser (key should be a valid folder in gadgets submodule)
gadget_type_mapping = {
    "python": PythonGadget,
}

converter_type_mapping = {
    "python": PythonConverter,
}