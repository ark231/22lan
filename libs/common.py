#!/usr/bin/env python3

from typing import TypedDict


class FuncBody(TypedDict):
    id: int
    content: str


class Code:
    _code: list[str]
    _indent: str

    def __init__(self, code=""):
        self._code = code.splitlines()
        self._indent = ""

    def add_line(self, line: str) -> None:
        self._code.append(f"{self._indent}{line}")

    def add_lines(self, lines: list[str]) -> None:
        self._code += lines

    def as_str(self) -> str:
        return "\n".join(self._code)

    def set_indent(self, indent: str) -> None:
        self._indent = indent

    def __getitem__(self, index: int) -> str:
        return self._code[index]

    def __add__(self, other) -> "Code":
        result = Code()
        result._code = self._code + other._code
        result._indent = other._indent
        return result

    @classmethod
    def as_code(cls, dct):
        if "__code__" in dct:
            result = Code()
            result._code = dct["code"]
            result.set_indent(dct["indent"])
            return result
        return dct

    def to_json_serializable(self):
        return {"__code__": True, "code": self._code, "indent": self._indent}
