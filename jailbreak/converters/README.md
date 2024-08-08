## Converters

These are converters that converts gadgets into variants if there are gadgets that can perform the operations needed.

On a gadget chain's creation, if a gadget doesn't match, it will be converted into possible variants before the gadget traversal continues.

The format is as follows:

```py
@register_converter(<ast node type that this applies to>, ...)
def <converter name>__<variant>(<ast node to be converted>, *, <required gadget>, ...):
    return <transformed ast, with gadget encoded in ast format>
```

### Usage

Converters are used automatically in the exploit chain generator as needed, but one can manually import the converters using `from jailbreak.converters.<subdirs> import <converter full name>`, similar to accessing raw gadgets.