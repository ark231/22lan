#!/usr/bin/env python3

import json
import toml
import sys
import argparse
from pathlib import Path
import csv
import re
from typing import cast, Final, ClassVar, NewType
import io
from enum import Enum, auto
from lark.lexer import Token
from logging import getLogger, config

logger = getLogger(__name__)

from langs import lan22_annotation, base
from libs import common
from libs.extension_resolver import ExtensionResolver
from libs.function_declaration_resolver import FuncDeclarationSolver
from libs.macro_resolver import retrieve_macros, from_macro, Macro

SUFFIXES: Final[dict[str, str]] = {
    "22lan": ".22l",
    "funcinfo": ".ext.csv",
    "22lan_extended": ".22le",
    "22lan_extended_library": ".22libe",
}


class ExtendedAnnotationParser(lan22_annotation.AnnotationParser):
    larkfile: ClassVar[Path] = Path(__file__).parent / "langs" / "extended_annotation.lark"


AUTOFUNC_STD_PATTERN = r";\\autofunc +std"
AUTOFUNC_USR_PATTERN = r";\\autofunc +usr"


def escape_extensions(filename: str, funcref=True, autofunc=True, pseudo_ops=True, macro=True) -> str:
    escaped = ""
    is_in_defmacro = False
    with open(filename, "r", encoding="utf-8") as infile:
        for line in infile:
            if funcref:
                line = re.sub("(@{(?P<func_name>[a-zA-Z0-9_]+)})", r";\1", line)
            if autofunc:
                line = re.sub(AUTOFUNC_STD_PATTERN, r";\\func -0b1", line)
                line = re.sub(AUTOFUNC_USR_PATTERN, r";\\func -0b10", line)
            if pseudo_ops:
                line = re.sub(r"( *)(\\.*)", r"\1;\2", line)
            if macro:
                if re.search(r"^ *#defmacro", line) is not None:
                    is_in_defmacro = True
                if re.search(r"^ *#endmacro", line) is not None:
                    is_in_defmacro = False
                line = re.sub(r"( *)(#.*)", r"\1;\2", line)
                if is_in_defmacro:
                    line = re.sub(r"( *)([^#].*)", r"\1;\2", line)
            escaped += line
    return escaped


def emit_funcinfo(args):
    escaped = escape_extensions(args.source)
    generator = lan22_annotation.FuncInfoTableGenerator(ExtendedAnnotationParser)
    generator.from_tree(base.Lan22Parser.parse(escaped))
    stream = io.StringIO()
    generator.dump(stream)
    reader = csv.reader(stream.getvalue().split("\n"))
    with open(args.output, "w", encoding="utf-8") as outfile:
        writer = csv.writer(outfile)
        header = next(reader)
        col_id = header.index("id")
        header.insert(col_id, "type")
        writer.writerow(header)
        for row in reader:
            if row == []:
                continue
            func_id = int(row[col_id], 0)
            if func_id == -1:
                func_type = "std"
                row[col_id] = "0"
            elif func_id == -2:
                func_type = "usr"
                row[col_id] = "0"
            else:
                func_type = "raw"
            row.insert(col_id, func_type)
            writer.writerow(row)


class FuncType(Enum):
    std = -1
    usr = -2


def check_implementation_exists(body: common.FuncBody) -> bool | None:
    startfunc_found: bool = False
    endfunc_found: bool = False
    for line in body["content"].splitlines():
        if re.search(r"^[^;]*startfunc", line) is not None:
            startfunc_found = True
        elif re.search(r"^[^;]*endfunc", line) is not None:
            endfunc_found = True
    if startfunc_found and endfunc_found:
        return True
    elif (startfunc_found and not endfunc_found) or ((not startfunc_found) and endfunc_found):
        return None
    else:
        return False


class AnnotationType(Enum):
    deffunc = auto()
    funcinfo = auto()
    other = auto()
    invalid = auto()


class AnnotationDistinguisher(lan22_annotation.AnnotationRetriever):
    type: AnnotationType
    info: dict[str, int | str]

    def __init__(self):
        super().__init__()
        self.type = AnnotationType.invalid
        self.info = {}

    def deffunc(self, nodes: list[Token]):
        self.type = AnnotationType.deffunc
        self.info["id"] = int(nodes[0].value, 0)

    def funcinfo(self, nodes: list[Token]):
        self.type = AnnotationType.funcinfo
        self.info["name"] = nodes[0].value

    def other(self, _):
        self.type = AnnotationType.other


def split_funcs(args) -> dict[str, common.FuncBody]:
    escaped = escape_extensions(args.source, funcref=False, pseudo_ops=False, macro=False)
    funcs: dict[str, common.FuncBody] = {"!!top!!": common.FuncBody(id=-2, content="")}
    current_name: str = "!!top!!"
    for line in escaped.splitlines(keepends=True):
        if re.search(";.*", line) is not None:
            distinguisher = AnnotationDistinguisher()
            distinguisher.from_tree(ExtendedAnnotationParser.parse(line.replace("\n", "")))
            if distinguisher.type == AnnotationType.deffunc:
                current_name = "!!new!!"
                funcs[current_name] = common.FuncBody(id=cast(int, distinguisher.info["id"]), content="")
            elif distinguisher.type == AnnotationType.funcinfo:
                current_name = cast(str, distinguisher.info["name"])
                funcs[current_name] = funcs["!!new!!"]
                funcs[current_name]["content"] += line
            else:
                funcs[current_name]["content"] += line
        else:
            funcs[current_name]["content"] += line
    if "!!new!!" in funcs:
        del funcs["!!new!!"]
    return funcs


ExtendedLan22Str = NewType("ExtendedLan22Str", str)
PureLan22Str = NewType("PureLan22Str", str)


def emit_22lan(args):
    funcs = split_funcs(args)
    for name, body in funcs.items():
        if name == "!!top!!":
            continue
        check_result = check_implementation_exists(body)
        if check_result is None:
            logger.warning("mismatching startfunc and endfunc in function '%s'", name)
        elif check_result is False:
            logger.warning("function '%s' doesn't have implementation", name)
    resolver = ExtensionResolver(args, funcs)

    with open(args.output, "w", encoding="utf-8") as outfile:
        resolver.resolve_all()
        outfile.write(resolver.code.as_str())


def emit_22lan_extended(args):
    funcs = split_funcs(args)
    for name, body in funcs.items():
        if name == "!!top!!":
            continue
        check_result = check_implementation_exists(body)
        if check_result is None:
            logger.warning("mismatching startfunc and endfunc in function '%s'", name)
        elif check_result is False:
            logger.warning("function '%s' doesn't have implementation", name)
    resolver = FuncDeclarationSolver(args, funcs)

    with open(args.output, "w", encoding="utf-8") as outfile:
        outfile.write(resolver.code.as_str())


def emit_22lan_extended_library(args):
    with open(args.source, "r", encoding="utf8") as infile:
        macros, _ = retrieve_macros(infile.read().splitlines())
    funcs: dict[str, int] = {}
    with open(args.funcinfo, "r", encoding="utf8") as infile:
        reader = csv.reader(infile)
        header = next(reader)
        name_idx = header.index("name")
        try:
            type_idx = header.index("type")
        except ValueError:
            type_idx = None
        id_idx = header.index("id")
        for row in reader:
            if row == []:
                continue
            func_name = row[name_idx]
            if type_idx is None:
                func_type = "raw"
            else:
                func_type = row[type_idx]
            match func_type:
                case "raw":
                    func_id = int(row[id_idx], 0)
                case "std":
                    func_id = int(f"0b11{int(row[id_idx],0):b}", 2)
                case "usr":
                    func_id = int(f"0b10{int(row[id_idx],0):b}", 2)
                case _:
                    func_id = -1
            funcs[func_name] = func_id

    class LibEncoder(json.JSONEncoder):
        def default(self, o):
            if isinstance(o, common.Code):
                return o.to_json_serializable()
            if isinstance(o, Macro):
                return from_macro(o)

    with open(args.output, "w", encoding="utf-8") as outfile:
        json.dump({"macros": macros, "funcs": funcs}, outfile, cls=LibEncoder)


def main():
    parser = argparse.ArgumentParser(
        description="resolve 22lan's function reference extention",
        prog="22lan_deref.py",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("-s", "--source", help="source file", required=True)
    parser.add_argument("-f", "--funcinfo", help="function information file")
    parser.add_argument("-e", "--external", help="external function information file(s)", nargs="+")
    parser.add_argument("-o", "--output", help="output filename (in result folder)")
    parser.add_argument("-l", "--lang", help="output language", choices=SUFFIXES.keys(), default="22lan")
    parser.add_argument("-d", "--debug", action="store_true", help="enable debug output")
    args = parser.parse_args()

    if args.output is None:
        args.output = Path(args.source).with_suffix(SUFFIXES[args.lang])
    if args.funcinfo is None:
        args.funcinfo = Path(args.source).with_suffix(".ext.csv")
    if Path(args.output) == Path(args.source):
        print("source and output is the same. are you sure to overwrite the source file?")
        while True:
            confirmed = input("y/n> ")
            match confirmed.lower():
                case "y":
                    break
                case "n":
                    sys.exit(0)

    match args.lang:
        case "22lan":
            emit_22lan(args)
        case "funcinfo":
            emit_funcinfo(args)
        case "22lan_extended":
            emit_22lan_extended(args)
        case "22lan_extended_library":
            emit_22lan_extended_library(args)


if __name__ == "__main__":
    config.dictConfig(toml.load(Path(__file__).parent / "log_config.toml"))
    main()
