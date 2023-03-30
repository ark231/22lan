#!/usr/bin/env python3

from lark.visitors import Transformer, Discard
from lark.tree import Tree
from lark.lexer import Token
from lark.lark import Lark
from pathlib import Path
from typing import NewType, ClassVar, TypeVar, Generic, cast
import base64


class ParseError(Exception):
    def __init__(self, message: str, linenum: int):
        super().__init__(message)
        self.linenum = linenum


ParsedTree = TypeVar("ParsedTree", bound=Tree)


class BasicGenerator(Transformer, Generic[ParsedTree]):
    def __init__(self, debug_level=0, backend_specific_args=None):
        super().__init__()
        self.debug_level = debug_level

    def from_tree(self, tree: ParsedTree) -> None:
        super().transform(tree)

    def dump(self, outputfile) -> None:
        outputfile.write(self.dumps())

    def dumps(self) -> str:
        return ""


ParseResult = TypeVar("ParseResult", bound=Tree)


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


class Stack:
    _value: int

    def __init__(self):
        self._value = 0

    def push1(self, value: int) -> None:
        self._value <<= 1
        self._value |= value

    def pop8(self) -> int:
        result = self._value & 0b1111_1111
        self._value >>= 8
        return result

    def pop64(self) -> int:
        result = self._value & 0xFFFF_FFFF_FFFF_FFFF
        self._value >>= 64
        return result


class BasicGeneratorFromLan22(BasicGenerator[Lan22Tree]):
    initial_stacks_base32: str
    compile_time_stack: Stack
    initial_s0: bytes
    initial_s1: bytes
    initial_s2: bytes

    def __init__(self, debug_level=0, backend_specific_args=None) -> None:
        super().__init__(debug_level=debug_level)
        self.initial_stacks_base32 = ""
        self.initial_s0 = b""
        self.initial_s1 = b""
        self.initial_s2 = b""
        self.compile_time_stack = Stack()
        self.functions = []

    def number(self, node: list[Token]) -> int:
        assert len(node) == 1
        return int(node[0].value, 0)

    def BASE32(self, node: str):
        self.initial_stacks_base32 += node
        return Discard

    def COMMENT(self, _: str):
        return Discard

    def _decompress_base32(self, b32str: str) -> str:
        result = ""
        prev_char = ""
        is_escaped = False
        is_repeat = False
        repeat = ""
        for char in b32str:
            if char == "\\":
                is_escaped = True
            elif is_escaped:
                if char in "OI2":
                    result += rf"\{char}"
                else:
                    if char == "S":
                        is_repeat = True
                    elif char == "E":
                        is_repeat = False
                        result += prev_char * (int(repeat.translate(str.maketrans("OI", "01")), 8) - 1)
                        repeat = ""
                    else:
                        result += rf"\{char}"
                is_escaped = False
            elif is_repeat:
                repeat += char
            else:
                prev_char = char
                result += char
        return result

    def _decode_stack_initializer(self):
        if self.initial_stacks_base32[0] != "\\":
            self.initial_stacks_base32 = r"\1" + self.initial_stacks_base32
        self.initial_stacks_base32 = self._decompress_base32(self.initial_stacks_base32)
        for initial_stack_base32 in self.initial_stacks_base32.split("\\"):
            if initial_stack_base32 == "" or len(initial_stack_base32) < 2:
                continue
            stack_id = "OI2".index(initial_stack_base32[0])
            current_value = getattr(self, f"initial_s{stack_id}")
            current_value += base64.b32decode(initial_stack_base32[1:] + "=" * (8 - len(initial_stack_base32[1:]) % 8))
            setattr(self, f"initial_s{stack_id}", current_value)
