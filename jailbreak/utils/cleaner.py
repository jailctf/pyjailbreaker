"""
This utility provides a cleaner function, which performs the following:
 - rewrites descriptive names into generated names using the character list given
 - (more to come, e.g. ast.unparse unnecessary artifacts removal etc)

NOTE: unless specified in the in_scope param of the cleaner function already, all name references will be rewritten, including builtin names
      since there is no way for this tool to automatically know what is in the scope or not given just the source
"""


# use __import__ to avoid tainting namespace
def cleaner(code, name_chars=__import__('string').ascii_lowercase, in_scope=[]):
    import ast, itertools

    tree = ast.parse(code)

    def name_generator():
        n = 1
        while True:
            yield from (''.join(group) for group in itertools.product(name_chars, repeat=n))
            n += 1
    
    def generate_name(gen = name_generator()):
        return next(gen)

    def apply(node: ast.AST, scope: dict):
        #convert names to names generated with chars in name_chars
        def convert_name(node: ast.AST, field: str):
            name = getattr(node, field)
            if name not in scope:
                scope[name] = generate_name()
            setattr(node, field, scope[name])
            print(scope)
        
        if isinstance(node, ast.Name):
            convert_name(node, 'id')
        elif isinstance(node, ast.arg):
            convert_name(node, 'arg')
        elif isinstance(node, ast.ExceptHandler):
            convert_name(node, 'name')
            
        #make a copy of the parent scope so edits on this scope wont affect the parent scope 
        elif isinstance(node, ast.FunctionDef):
            #convert name first so its in the parent scope before narrowing scope
            convert_name(node, 'name')
            scope = dict(scope)

        #do not rewrite imported names
        elif isinstance(node, ast.alias):
            #if we aliased the import, rewrite that name
            if node.asname:
                convert_name(node, 'asname')
            #otherwise keep the names in the mapping, we cannot rename it
            else:
                scope[node.name] = node.name
        
        return node, scope

    #altered from NodeTransformer to track scoping
    #XXX now that i think about it there doesnt seem to be any reason to track scope
    #    since even if the names collide the runtime would handle it for all the valid cases
    #    and the invalid cases doesnt work in the original code anyways
    #    so a global renamer with no care about scoping would work just as well
    def visit(curr: ast.AST, scope: dict):
        curr, scope = apply(curr, scope)

        for field in curr._fields:
            try:
                attr = getattr(curr, field)
                if isinstance(attr, list):
                    for i, node in enumerate(attr):
                        if isinstance(node, ast.AST):
                            attr[i] = visit(node, scope)
                elif isinstance(attr, ast.AST):
                    setattr(curr, field, visit(attr, scope))
            except AttributeError:
                pass
        return curr
        
    return ast.unparse(visit(tree, {n: n for n in in_scope}))