import sys
from urwid import WidgetMeta, Frame
from .config import Action, Key


def KeyHandler(f):
    def m(self, *args, **kwargs):
        return f(self, *args, **kwargs)

    m.__doc__ = f.__doc__
    m.is_ui_method = True
    return m


class InteractableMeta(WidgetMeta):
    def __new__(cls, name, bases, attrs):
        ms = {}
        for k, v in attrs.items():
            try:
                if v.is_ui_method:
                    ms[k] = v
                pass
            except AttributeError:
                continue
        attrs["ui_methods"] = ms

        def _help(config):
            context = name.lower()
            keys = config["binds"][context]
            bound = set(str(b) for b in keys.values() if isinstance(b, Action))
            unbound = set(ms.keys()) - bound
            yield (None, "", f"{name} commands:")
            for k, b in keys.items():
                if isinstance(b, Action):
                    bstr = str(b)
                    doc = ms[bstr].__doc__
                    yield (k, bstr, ms[bstr].__doc__)
            if len(unbound) > 0:
                yield (None, "", f"Unbound {cname} commands: ")
                for c in unbound:
                    yield (" ", c, ms[c].__doc__)
        attrs["_help"] = _help

        return super(InteractableMeta, cls).__new__(cls, name, bases, attrs)


class Interactable:
    def keypress(self, size, key):
        passthrough = super(Interactable, self).keypress(size, key)
        if not passthrough:
            return None
        context = self.__class__.__name__.lower()
        keys = self.config["binds"][context]
        if key in keys:
            bind = keys[key]
            bstr = str(bind)
            if isinstance(bind, Action):
                try:
                    return self.ui_methods[bstr](self, size, key)
                except KeyError as e:
                    pass
            elif isinstance(bind, Key):
                return self.keypress(size, bstr)
        return key
