"""
Gadgets for obtaining obj.__dict__ for arbitrary objects
"""

def get_obj_dict__basic(obj):
    return obj.__dict__

def get_obj_dict__vars(obj, *, vars):
    return vars()(obj)