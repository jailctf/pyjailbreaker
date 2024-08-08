## Gadgets

This is the core of this repo. It documents all the known methods of performing a step in a chain, be it obtaining a class, running a function, etc - with each gadget using a set of required gadgets, if any, to achieve the results.

Each file stores a specific type of gadget for performing the equivalent operation, in the following format:

```py
def <gadget function name>__<variant name>(<param1>, ..., *, <required gadget function name>, ...):
    #the below fields, or even the whole docstring itself, could be missing to signify all platforms and versions are supported.
    """
        platforms: ["windows", "mac", "linux"]  #enum of platform choices, only possible choices at the moment
        versions: [10, 11, 12]  #list of versions with the format 3.xx, example only
    """
    return <any value that it has to return, or None>
```

The gadget function names should match the file name that it resides in for easy lookup, and the file name should match an existing python function/attribute if the functionality is equivalent.

### Usage

Importing a gadget using `from jailbreak import <gadget function name>` will trigger the searcher to perform a traversal with the configured restrictions.

One can configure the restrictions by calling the following function:

```py
import jailbreak
import ast, pickle

jailbreak.config(
    ast=[ast.CALL, ...],                    # a list of ast nodes to be banned
    pickle=[pickle.REDUCE, ...],            # a list of pickle ops to be banned
    char='ABCDEF...',                       # a string of all characters to be banned
    platforms=["windows", "mac", "linux"],  # see above
    versions=[10, 11, 12],                  # see above
    provided=["<gadget name>", ...],        # list of gadgets that is already provided (e.g. if builtins chr is provided, put chr here)
)

chain = jailbreak.<gadget function name>  #returns a string object representing the code generated, or throws an error with the closest string object (closest == least restriction violations)
```

The restrictions only adds up at the moment - all of the criteria has to be met for the gadget to be deemed usable.


Outside of the exploit chain generator, if a specific gadget is required either for manual chain creation, inspection, or testing, `from jailbreak.gadgets.<subdirs> import <gadget full name>` could be used instead.