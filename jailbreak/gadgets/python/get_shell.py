"""
Gadgets for obtaining a shell.
"""


#basic get shell
def get_shell__os_system(cmd, *, os):
    os.system(cmd)



#get shell with exec
def get_shell__exec(cmd, *, exec):
    exec(cmd)

