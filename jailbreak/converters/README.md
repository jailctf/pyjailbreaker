## Converters

These are converters that converts gadgets into variants if there are gadgets that can perform the operations needed.

On a gadget chain's creation, if a gadget doesn't match, it will be converted into possible variants before the gadget traversal continues.

The format is as follows:

```py
@register_converter(<ast node type that this applies to>, ..., ast=[<list of nodes that this converter hides>], char=[<list of chars that this converter hides>], ...)
def <converter name>__<variant>(<ast node to be converted>, *, <required gadget>, ...):
    return <transformed ast, with gadget encoded in ast format>
```

The args on register_convert refers to the node type(s) that this converter transforms (which is also provided to the converter as the first param); whereas the kwargs specify what violations should trigger this converter.
The more specific the violations are, the less time it requires for the gadget traverser to work - converters could potentially make the search space exponentially larger due to generating new gadgets variants on the fly.

Converters are only chosen if it meets all of the below requirements, on a gadget that violates the configured jail restrictions:
- the converter is applicable for at least one of the jail restrictions
- the converter does not depend on gadget(s) with a chain that violates the jail restrictions

They are then applied in all permutations of ordering; each newly rewritten function after the applications will be checked again for violations in case of regressions.

Converters should attempt to not introduce new regressions that require running another converter to fix - this is not supported (and also unlikely in the future due to the exponential search space) and the gadget chain will simply fail.

There should be no subdirectory in the converters directory - all files containing converters should be at the root directory for correct importing.

### Usage

Converters are used automatically in the exploit chain generator as needed, but one can manually import the converters using `from jailbreak.converters.<subdirs> import <converter full name>`, similar to accessing raw gadgets.