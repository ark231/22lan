#!/usr/bin/env python3

from lark.visitors import Discard, v_args
from lark.tree import Tree
from lark.lexer import Token
from pathlib import Path
import csv
from . import base
import io
from typing import cast, TypedDict, NewType


class FuncInfo(TypedDict):
    name: str
    id: str
    args: list[str]
    retvals: list[str]


AnnotationTree = NewType("AnnotationTree", Tree)


class AnnotationParser(base.BasicParser[AnnotationTree]):
    larkfile = Path(__file__).parent / "annotation.lark"


class AnnotationRetriever(base.BasicGenerator[AnnotationTree]):
    def __init__(self):
        super().__init__()
        self.funcs: list[FuncInfo] = []

    def type_list(self, nodes: list[Token]) -> list[str]:
        return [] if nodes[0].type == "NONE" else [node.value for node in nodes]

    def deffunc(self, nodes: list[Token]):
        self.funcs.append({"name": "", "id": nodes[0].value, "args": [], "retvals": []})
        return Discard

    def funcinfo(self, nodes: list[Token | list[str]]):
        self.funcs[-1]["name"] = cast(Token, nodes[0]).value
        self.funcs[-1]["args"] = cast(list[str], nodes[1])
        self.funcs[-1]["retvals"] = cast(list[str], nodes[2])
        return Discard


class FuncInfoTableGenerator(base.BasicGenerator[base.Lan22Tree]):
    def __init__(self, parser: type[base.BasicParser] = AnnotationParser, debug_level=0):
        super().__init__(debug_level=debug_level)
        self.retriever = AnnotationRetriever()
        self.parser = parser

    @v_args(meta=True)
    def start(self, meta, nodes: list[Token | base.Lan22Tree]):
        for node in nodes:
            if not isinstance(node, Token):
                continue
            if node.type == "COMMENT":
                try:
                    self.retriever.from_tree(self.parser.parse(node.value))
                except Exception as err:
                    raise base.ParseError(str(err), meta.line)

    def dumps(self) -> str:
        result = ""
        max_num_args = max(len(func["args"]) for func in self.retriever.funcs)
        max_num_retvals = max(len(func["retvals"]) for func in self.retriever.funcs)
        for func in self.retriever.funcs:
            assert isinstance(func["args"], list) and isinstance(func["retvals"], list)
            func["args"] += [""] * (max_num_args - len(func["args"]))
            func["retvals"] += [""] * (max_num_retvals - len(func["retvals"]))
        with io.StringIO() as stream:
            writer = csv.writer(stream)
            writer.writerow(
                ["name", "id"]
                + [f"arg{i}" for i in range(max_num_args)]
                + [f"retval{i}" for i in range(max_num_retvals)]
            )
            for func in self.retriever.funcs:
                writer.writerow(
                    [func["name"], func["id"]] + cast(list[str], func["args"]) + cast(list[str], func["retvals"])
                )
            result = stream.getvalue()
        return result

    @property
    def retrieved_funcs(self) -> list[FuncInfo]:
        return self.retriever.funcs
