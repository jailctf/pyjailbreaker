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
import ast as _ast, inspect as _inspect, copy as _copy


#
# Utility functions/classes
#

#TODO convenience function for creating gadget classes with just name (given a list of gadgets)


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
    
    def generic_visit(self, node: _ast.AST) -> _ast.AST:
        if type(node) in self.applies:
            node = _ast.fix_missing_locations(self.converter(node))
        
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
    #NOTE: func should not change even if it is rewritten
    func: _FunctionType = _field(repr=False)  #no useful info to repr here, hide it
    name: str = _field(init=False)
    #all dependencies of a gadget of subclass should have dependencies of also the same subclass
    dependencies: 'list[GadgetBase]' = _field(default_factory=list)
    dummy: bool = _field(default=False, init=False)
    #TODO some mechanism to track failed gadget chains for giving partial suggestions

    #TODO run add_dependency (and similar funcs, eg apply_converters) on post init so the raw data is properly converted

    #create a dummy gadget - child classes should override it to provide dummy data for their respective types
    @classmethod
    def create_dummy_gadget(cls, name: str):
        def dummy(): pass
        gadget = cls(dummy)
        gadget.name = name
        gadget.dummy = True
        return gadget

    def __post_init__(self):
        self.name = self.func.__name__

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

    #NOTE: child classes should extend these for converters to use the raw data properly

    #extract data for converters
    #NOTE: should make a COPY since the data could be discarded
    def extract(self):
        return None

    #apply the converters, along with raw data that weve converted
    #NOTE: ALL converters in this list should be the same type
    def apply_converters(self, converters: 'list[ConverterBase]', data):
        self.converters += converters


#documents an converter
@_dataclass(eq=False)
class ConverterBase(ModelBase):
    #what data this converter applies to
    applies: list = _field(default_factory=list)

    #we must make applies default due to how dataclasses work, so assert here just to make sure
    def __post_init__(self):
        super().__post_init__()
        assert self.applies, "applies is empty"

    #attempts to convert some raw data using this converter
    #NOTE: raw data since we dont want to change the gadget itself at this stage,
    #      we are just testing and the data could be discarded
    def convert(self, data):
        pass



#documents a python converter
@_dataclass(eq=False)
class PythonConverter(ConverterBase):
    def convert(self, data: _ast.AST):
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
    @classmethod
    def create_dummy_gadget(cls, name: str):
        #NOTE ast trees dont have a node for comments, but we can abuse Name nodes since there are no validity checking
        #NOTE need to wrap in Expr so its in a new line
        gadget = super().create_dummy_gadget(name)
        gadget.func_ast = _ast.Module([_ast.Expr(_ast.Name(f'#def {name}(*args, **kwargs): pass  #TODO provided'))], [])
        gadget.orig_ast = _copy.deepcopy(gadget.func_ast)
        return gadget


    #override: also initialize func_ast for this gadget
    def __post_init__(self):
        super().__post_init__()
        self.func_ast = _ast.parse(_inspect.getsource(self.func).strip())  #strip to accomodate for nested function sources (e.g. the one at create_dummy_gadget)
        self.orig_ast = _copy.deepcopy(self.func_ast)
        self.chain_ast = _ast.Module([], []) if not self.inline else self.func_ast #empty container if not inline else same ref as func_ast coz the chain directly modifies the func_ast

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

            #remove gadget docstrings if any (ref: ast.get_docstring)
            #body of the functiondef, should at least have one element or else its an invalid function anyway
            first_func_body_node = self.orig_ast.body[0].body[0]  #NOTE: use orig_ast since func_ast couldve been modified by this time
            if isinstance(first_func_body_node, _ast.Expr) and isinstance(first_func_body_node.value, _ast.Constant) and isinstance(first_func_body_node.value.value, str): 
                #find the equivalent docstring in full_ast and remove it
                for stmt in full_ast.body[0].body:
                   if isinstance(stmt, _ast.Expr) and isinstance(stmt.value, _ast.Constant) and isinstance(stmt.value.value, str) and stmt.value.value == first_func_body_node.value.value:
                       full_ast.body[0].body.remove(stmt)
                       break
                       

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
    def apply_converters(self, converters: 'list[ConverterBase]', data: _ast.AST):
        super().apply_converters(converters, data)
        #replace func_ast with the new data we computed
        self.func_ast = data
        if self.inline:
            self.chain_ast = self.func_ast  #also need to update chain_ast's reference to use the new one
        for converter in converters:
            for dep in converter.dependencies:
                #make type hinting work again while enforcing the dependency assumption
                assert isinstance(dep, type(self)), f'dep is of type {type(dep)}, not {type(self)}!'
                #the chain is basically cached already in dep.chain_ast, no need to worry about performance
                self._put_code_into_func_body(self.chain_ast, dep.get_full_ast())


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