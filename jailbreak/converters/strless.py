from .. import register_converter
import ast, functools

"""
Removes the requirement for strings if possible.
"""

# converts ints to strings via chr
@register_converter(ast.Constant, char='\'"', ast=[ast.Constant])  #highly doubt the constant rule would match ever, since a jail with a constant check seems overkill anyway
def strless__chr(path, *, chr):
    #parent must exist since first element must always be an ast.Module, but check it anyways
    strnode, parent = path[-1], path[-2]

    #only transform if its a string node
    if isinstance(strnode.value, str):
        #convert to chr(ascii) + chr(ascii) + ... calls
        converted = functools.reduce(lambda x, y: ast.BinOp(x, ast.Add(), y), [ast.Call(ast.Name('chr', ast.Load()), [ast.Constant(ord(c))], []) for c in strnode.value])

        #f-strings have slightly different expectations
        if isinstance(parent, ast.JoinedStr):
            #if this is a part of an f-string constant, need to convert this into a formatted value with no formatting required
            if strnode in parent.values:
                return ast.FormattedValue(converted, -1, None)
            #if this is a part of an f-string format_spec, ignore
            elif len(path) >= 3 and isinstance(path[-3], ast.FormattedValue) and path[-3].format_spec == parent: 
                return strnode
            
        #otherwise we are good to convert
        return converted
    return strnode