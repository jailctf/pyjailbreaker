import jailbreak

# from jailbreak.gadgets.python import get_builtins
# print(get_builtins.get_builtins__gi_builtins())

jailbreak.config(provided=['get_sys'])

import sys

payload = jailbreak.get_shell

print(payload)

exec(payload, {'__builtins__': {}, 'get_sys': lambda: sys})