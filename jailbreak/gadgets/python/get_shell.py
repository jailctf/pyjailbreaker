"""
Gadgets for obtaining a shell.
"""


#basic get shell
def get_shell__os_system(*, get_os):
    get_os().system('sh')



#get shell with exec
def get_shell__exec(*, exec):
    exec('import os; os.system("sh")')

