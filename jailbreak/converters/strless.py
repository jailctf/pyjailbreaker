#we dont really care about polluting the namespace here much since we have @register_converter so we dont need to scrape namespace
from .. import register_converter
import ast, functools

"""
Removes the requirement for strings if possible.
"""

#helps handle f-strings and such
def _common_strless_helper(path, convert_func):
    #parent must exist since first element must always be an ast.Module, but check it anyways
    strnode, parent = path[-1], path[-2]

    #only transform if its a string node
    if isinstance(strnode.value, str):
        #convert to chr(ascii) + chr(ascii) + ... calls
        converted = convert_func(strnode)

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



# converts ints to strings via chr
#TODO: probably run this on wildcard substr violation in an attempt to remove banned things from strings? since this converts strings to something completely diff with chr() + chr() + ...
@register_converter(ast.Constant, char='\'"', ast=[ast.Constant])  #highly doubt the constant rule would match ever, since a jail with a constant check seems overkill anyway
def strless__chr(path, *, chr):
    convert_func = lambda strnode: functools.reduce(lambda x, y: ast.BinOp(x, ast.Add(), y), [ast.Call(ast.Name('chr', ast.Load()), [ast.Constant(ord(c))], []) for c in strnode.value])
    return _common_strless_helper(path, convert_func)


@register_converter(ast.Constant, char='\'"', ast=[ast.Constant])
def strless__kwargs(path):
    def convert_func(strnode):
        if strnode.value.isidentifier():
            replacement = ast.parse('[*(lambda**k:k)(STRHERE=1)][0]')
            #replace STRHERE with string
            replacement.body[0].value.value.elts[0].value.keywords[0].arg = strnode.value
            return replacement
        else:
            #cant use this converter, return the same node
            return strnode

    return _common_strless_helper(path, convert_func)
