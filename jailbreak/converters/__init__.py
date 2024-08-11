#load all converters dynamically (after all definitions are defined here) so @register_converter triggers
if '__path__' in globals():  #first time import only, no need to run again on the importlib.import_module calls
    import importlib, os

    for path, _, filenames in os.walk(__path__[0]):
        for f in filenames:
            filename, ext = os.path.splitext(f.lower())
            if ext == '.py':
                globals()[filename] = importlib.import_module('.' + filename, __name__)
        
        #clean up so these vars don't pollute the module
        del f, filename, ext, path, _, filenames

    del importlib, os