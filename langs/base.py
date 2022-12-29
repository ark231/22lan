#!/usr/bin/env python3

from lark.visitors import Transformer
from lark.tree import Tree
from lark.lark import Lark
from pathlib import Path
from typing import NewType, ClassVar, TypeVar, Generic, cast


class ParseError(Exception):
    def __init__(self, message: str, linenum: int):
        super().__init__(message)
        self.linenum = linenum


ParseResult = TypeVar("ParseResult", bound=Tree)


class BasicGenerator(Transformer, Generic[ParseResult]):
    def __init__(self):
        super().__init__()

    def from_tree(self, tree: ParseResult) -> None:
        super().transform(tree)

    def dump(self, outputfile) -> None:
        outputfile.write(self.dumps())

    def dumps(self) -> str:
        return ""


class BasicParser(Generic[ParseResult]):
    larkfile: ClassVar[Path] = Path()

    @classmethod
    def parse(cls, source: str) -> ParseResult:
        with open(cls.larkfile, "r", encoding="utf8") as larkfile:
            parser = Lark(larkfile.read(), propagate_positions=True)
        return cast(ParseResult, parser.parse(source))


Lan22Tree = NewType("Lan22Tree", Tree)


class Lan22Parser(BasicParser[Lan22Tree]):
    larkfile = Path(__file__).parent / "22lan.lark"
