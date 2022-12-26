#!/usr/bin/env python3

from lark.visitors import Discard, v_args
from lark.lexer import Token
from pathlib import Path
import csv
from . import base
import io
from typing import cast


class AnnotationRetriever(base.BasicGenerator):
    def __init__(self):
        super().__init__()
        self.funcs: list[dict[str, str | list[str]]] = []

    def FUNC_ID(self, node: str) -> str:
        return node

    def FUNC_NAME(self, node: str) -> str:
        return node

    def TYPE(self, node: str) -> str:
        return node

    def type_list(self, nodes: list[Token]) -> list[str]:
        return [] if nodes[0].type == "NONE" else [node.value for node in nodes]

    def deffunc(self, nodes: list):
        self.funcs.append({"id": nodes[0]})
        return Discard

    def funcinfo(self, nodes: list[str | list[str]]):
        self.funcs[-1]["name"] = nodes[0]
        self.funcs[-1]["args"] = nodes[1]
        self.funcs[-1]["retvals"] = nodes[2]
        return Discard


class FuncInfoTableGenerator(base.BasicGenerator):
    def __init__(self):
        super().__init__()
        self.retriever = AnnotationRetriever()

    @v_args(meta=True)
    def line(self, meta, nodes: list[Token]):
        comment_node = None
        for node in nodes:
            if node.type == "COMMENT":
                comment_node = node.value
        if comment_node is None:
            return Discard
        try:
            self.retriever.from_tree(AnnotationParser.parse(comment_node))
        except Exception as err:
            raise base.ParseError(str(err), meta.line)
        return Discard

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


class AnnotationParser(base.BasicParser):
    larkfile = Path(__file__).parent / "annotation.lark"
