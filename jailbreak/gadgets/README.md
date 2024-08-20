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