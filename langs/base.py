#!/usr/bin/env python3

from lark.visitors import Transformer
from lark.tree import Tree
from lark.lark import Lark
from pathlib import Path


class ParseError(Exception):
    def __init__(self, message: str, linenum: int):
        super().__init__(message)
        self.linenum = linenum


class BasicGenerator(Transformer):
    def __init__(self):
        super().__init__()

    def from_tree(self, tree: Tree) -> None:
        super().transform(tree)

    def dump(self, outputfile) -> None:
        outputfile.write(self.dumps())

    def dumps(self) -> str:
        return ""


class BasicParser:
    larkfile: Path = Path()

    @classmethod
    def parse(cls, source: str) -> Tree:
        with open(cls.larkfile, "r", encoding="utf8") as larkfile:
            parser = Lark(larkfile.read(), propagate_positions=True)
        return parser.parse(source)


class Lan22Parser(BasicParser):
    larkfile = Path(__file__).parent / "22lan.lark"
