from lark.lark import Lark
from lark.visitors import Transformer
import sys
from importlib import resources

import sympy


class Bnet2Sympy(Transformer):
    def __init__(self):
        self.symbols = {}

    def bnet(self, items):
        result = dict(items)
        # Remove the "targets,factors" pair
        targets = self.symbols.get("targets")
        factors = self.symbols.get("factors")
        if factors and result.get(targets) == factors:
            del result[targets]
            del self.symbols["targets"]
            if factors is not None:
                del self.symbols["factors"]
        symbols = tuple(sorted(self.symbols.values(), key=lambda s: s.name))
        return result, symbols

    def function(self, items):
        return items[0], items[1]

    def atom(self, items):
        return items[0]

    def BANG(self, _):
        return "!"

    def negation(self, items):
        if len(items) % 2:
            return items[-1]
        return ~(items[-1])

    def expr(self, items):
        if len(items) == 1:
            return items[0]
        return sympy.Or(*items)

    def conjunction(self, items):
        if len(items) == 1:
            return items[0]
        return sympy.And(*items)

    def FALSE(self, _):
        return sympy.false

    def TRUE(self, _):
        return sympy.true

    def IDENTIFIER(self, item):
        if item.value not in self.symbols:
            self.symbols[item.value] = sympy.symbols(f"{item.value}")
        return self.symbols[item.value]


def bnet2sympy(fname: str) -> tuple[dict, tuple]:
    grammar = resources.read_text("bnet2hoa", "bnet.lark")
    parser = Lark(
        grammar, start="bnet", parser="lalr", transformer=Bnet2Sympy())
    return parser.parse(open(fname).read())


def main():
    trel, symbols = bnet2sympy(sys.argv[1])
