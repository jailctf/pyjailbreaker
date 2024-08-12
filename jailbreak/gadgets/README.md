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

Currently, the gadget code has to be formatted in a very specific way for the gadget rewrites to work:
- the function definition must be on a single line
- the lines of code must be indented using 4-spaces
This is chosen to avoid too much rewriting on the gadget codes themselves to preserve their properties (e.g. characters used). Better schemes of rewriting will be investigated in the future.

Raw gadgets, such a pickle and bytecode gadgets, is of a slightly different format - the code of the gadget is responsible for creating the part of raw bytes that the gadget is responsible. Thus, its return value should be bytes, and the whole gadget chain will be run to obtain the full payload instead of returning the full code of the chain like a python gadget chain would have.

If a gadget requires a functionality from another gadget, it should put the required gadget function name in the kwargs of the function parameter list. If the gadget requires no params, it is simply usable as a variable. otherwise, call the gadget with the required params for the return value.


The following resolution flow will be run for the required gadgets:
- check if it is in the `provided` field set in `config()`, if so use that
- check if the function name match any file name specified, if so attempt to use the gadgets defined inside the file
  - for each gadget function defined in the file:
    - attempt to continue the traversal by resolving the requirements for that gadget and whether it violates the restrictions set in `config`
    - if it fails, for each converter that exists:
      - traverse the gadgets required for the converter first, if possible then run the conversion, and attempt to continue the traversal using the newly generated gadget 


Thus, the gadget function names should match the file name that it resides in, and the file name should match an existing python function/attribute if the functionality is equivalent.
Since builtins functions are the most commonly used, there is a separate directory to store those gadgets to avoid cluttering.

### Usage

Importing a gadget using `from jailbreak import <gadget function name>` will trigger the searcher to perform a traversal with the configured restrictions.

One can configure the restrictions by calling the following function:

```py
import jailbreak
import ast, pickle

jailbreak.config(
    ast=[ast.CALL, ...],                    # a list of ast nodes to be banned
    char='ABCDEF...',                       # a string of all characters to be banned
    platforms=["windows", "mac", "linux"],  # see above
    versions=[10, 11, 12],                  # see above
    pickle=[pickle.REDUCE, ...],            # a list of pickle ops to be banned
    provided=["<gadget name>", ...],        # list of gadgets that is already provided, including any names of builtins already provided.
)

#returns a string object representing the code generated, or throws an error with the closest string object (closest == least restriction violations)
#params (can be empty) are for the last gadget in the gadget chain (aka the one requested by the user), and are python code in string form for flexibility
#NOTE: all params passed are unverified since it is direct user given code and is deemed usable out of the box
chain = jailbreak.<gadget function name>(<param1>, ...)  
```

The restrictions only adds up at the moment - all of the criteria has to be met for the gadget to be deemed usable.


Outside of the exploit chain generator, if a specific gadget is required either for manual chain creation, inspection, or testing, `from jailbreak.gadgets.<subdirs> import <gadget full name>` could be used instead.

A user is also able to provide their own gadgets through providing their own python function that confirms to the gadget spec via `jailbreak.register_user_gadget(<gadget function object>, <gadget type (aka the directory names in gadgets/, e.g. "python")>)`.