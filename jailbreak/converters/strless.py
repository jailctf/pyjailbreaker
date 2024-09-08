from .. import register_converter
import ast, functools

"""
Removes the requirement for strings if possible.
"""

# converts ints to strings via chr
@register_converter(ast.Constant, char='\'"', ast=[ast.Constant])  #highly doubt the constant rule would match ever, since a jail with a constant check seems overkill anyway
def strless__chr(strnode, *, chr):
    #only transform if its a string node
    if isinstance(strnode.value, str):
        return functools.reduce(lambda x, y: ast.BinOp(x, ast.Add(), y), [ast.Call(ast.Name('chr', ast.Load()), [ast.Constant(ord(c))], []) for c in strnode.value])
    return strnode