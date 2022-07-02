import os
import sys
from pathlib import Path
from lark import Lark, Transformer

grammar = """
    %import common.CNAME
    %import common.NEWLINE
    %import common.WS_INLINE
    %import common.SH_COMMENT
    %ignore WS_INLINE
    CONTEXT: "ui"i | "search"i | "prompt"i | "document"i | "help"i | "bibview"i
    SPECIAL: "enter"i | "space"i | "tab"i | "backspace"i
        | "insert"i | "delete"i | "home"i | "end"i | "pgup"i | "pgdn"i
        | "up"i | "down"i | "left"i | "right"i
        | "f"i (/[1-9]/ | "10" | "11" | "12")
    bind: "bind" CONTEXT? key rhs
    MODIFIER: "ctrl"i | "shift"i | "meta"i
    key: (MODIFIER "-")? /\S/
        | SPECIAL
    ?rhs: "<" key ">"
        | CNAME -> action
    ?statement: bind
    config: NEWLINE* (statement NEWLINE+)*
"""


class Config:
    def __init__(self):
        dirs = []
        cfname = "config"
        defaultfname = "default.config"
        defaultpath = Path(__file__).with_name(defaultfname)
        with defaultpath.open() as f:
            confstr = f.read() + "\n"
        try:
            dirs.append(Path(os.environ["XDG_CONFIG_HOME"]) / "xapers")
        except AttributeError:
            pass
        try:
            home = Path(os.environ["HOME"])
            dirs.append(home / ".config" / "xapers")
            dirs.append(home / ".xapers")
        except AttributeError:
            pass
        for d in dirs:
            try:
                with (d / cfname).open() as f:
                    confstr += f.read()
            except IOError:
                continue
            else:
                break
        confparser = Lark(grammar, start="config")
        conftrans = ConfigTransformer()
        parsetree = confparser.parse(confstr)
        self.conf = conftrans.transform(parsetree)

    def __getitem__(self, key):
        return self.conf[key]


class Bind:
    def __init__(self, children):
        self.context = "ui"
        offset = 0
        if len(children) > 2:
            self.context = str(children[0])
            offset = 1
        self.key = children[0 + offset]
        self.rhs = children[1 + offset]

    def __str__(self):
        return f"Bind({self.context}, {self.key}, {self.rhs})"


class Action:
    def __init__(self, action):
        self.action = action

    def __repr__(self):
        return f"Action({self.action})"

    def __str__(self):
        return str(self.action)


class Key:
    def __init__(self, key):
        self.key = key

    def __repr__(self):
        return f"Key({self})"

    def __str__(self):
        return " ".join(self.key)


class ConfigTransformer(Transformer):

    CNAME = str
    bind = Bind
    action = lambda _, a: Action(a[0])
    key = Key

    def config(self, children):
        out = {}
        binds = {}
        for c in children:
            if isinstance(c, Bind):
                binds.setdefault(c.context, {})
                binds[c.context][str(c.key)] = c.rhs
        out["binds"] = binds
        return out
