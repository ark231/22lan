#!/usr/bin/env python3

import sys
import argparse
from pathlib import Path
import csv
import re
from langs import lan22_annotation, base
from typing import cast, Final, ClassVar, TypedDict, NewType
import io
from enum import Enum, auto
from lark.lexer import Token

SUFFIXES: Final[dict[str, str]] = {"22lan": ".22l", "funcinfo": ".ext.csv"}


class ExtendedAnnotationParser(lan22_annotation.AnnotationParser):
    larkfile: ClassVar[Path] = Path(__file__).parent / "langs" / "extended_annotation.lark"


AUTOFUNC_STD_PATTERN = r";\\autofunc +std"
AUTOFUNC_USR_PATTERN = r";\\autofunc +usr"


def escape_extensions(filename: str, funcref=True, autofunc=True) -> str:
    escaped = ""
    with open(filename, "r", encoding="utf-8") as infile:
        for line in infile:
            if funcref:
                line = re.sub("(@{(?P<func_name>[a-zA-Z0-9_]+)})", r";\1", line)
            if autofunc:
                line = re.sub(AUTOFUNC_STD_PATTERN, r";\\func -0b1", line)
                line = re.sub(AUTOFUNC_USR_PATTERN, r";\\func -0b10", line)
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


class FuncBody(TypedDict):
    id: int
    content: str


def check_implementation_exists(body: FuncBody) -> bool | None:
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


def split_funcs(args) -> dict[str, FuncBody]:
    escaped = escape_extensions(args.source, funcref=False)
    funcs: dict[str, FuncBody] = {"!!top!!": FuncBody(id=-2, content="")}
    current_name: str = "!!top!!"
    for line in escaped.splitlines(keepends=True):
        if re.search(";.*", line) is not None:
            distinguisher = AnnotationDistinguisher()
            distinguisher.from_tree(ExtendedAnnotationParser.parse(line.replace("\n", "")))
            if distinguisher.type == AnnotationType.deffunc:
                current_name = "!!new!!"
                funcs[current_name] = FuncBody(id=cast(int, distinguisher.info["id"]), content="")
            elif distinguisher.type == AnnotationType.funcinfo:
                current_name = cast(str, distinguisher.info["name"])
                funcs[current_name] = funcs["!!new!!"]
                funcs[current_name]["content"] += line
            else:
                funcs[current_name]["content"] += line
        else:
            funcs[current_name]["content"] += line
    del funcs["!!new!!"]
    return funcs


Lan22WithFuncrefStr = NewType("Lan22WithFuncrefStr", str)
PureLan22Str = NewType("PureLan22Str", str)


def resolve_autofuncs(args, funcs: dict[str, FuncBody]) -> Lan22WithFuncrefStr:
    if args.funcinfo is None:
        print("error: source file contains autofunc, but no funcinfo file was supplied", file=sys.stderr)
        sys.exit(1)
    result = funcs["!!top!!"]["content"]
    del funcs["!!top!!"]
    funcnames_in_funcinfo: list[str] = []
    with open(args.funcinfo, "r", encoding="utf-8") as infile:
        reader = csv.reader(infile)
        header = next(reader)
        name_idx = header.index("name")
        type_idx = header.index("type")
        id_idx = header.index("id")
        arg0_idx = header.index("arg0") if "arg0" in header else None
        retval0_idx = header.index("retval0") if "retval0" in header else None
        for row in reader:
            if row == []:
                continue
            try:
                func = funcs[row[name_idx]]
                match row[type_idx]:
                    case "raw":
                        result += rf";\func {int(row[id_idx],0):#b}"
                        funcs[row[name_idx]]["id"] = int(row[id_idx], 0)
                    case "std":
                        result += rf";\func 0b11{int(row[id_idx],0):b}"
                        funcs[row[name_idx]]["id"] = int(f"0b11{int(row[id_idx],0):b}", 2)
                    case "usr":
                        result += rf";\func 0b10{int(row[id_idx],0):b}"
                        funcs[row[name_idx]]["id"] = int(f"0b10{int(row[id_idx],0):b}", 2)
                    case _:
                        print(f"error: unknown functype '{row[type_idx]}'")
                        result += rf";!error func from_annotation: {func['id']}, from funcinfo file: {row[id_idx]}"
                result += "\n"
                result += func["content"]
                funcnames_in_funcinfo.append(row[name_idx])
            except KeyError:
                print(f"warn: func '{row[name_idx]} is in funcinfo file, but not in source code, thus not implemented'")
                result += rf";\func {int(row[id_idx],0):#b}"
                result += "\n"
                if arg0_idx is None:
                    args = None
                else:
                    args = []
                    for i in range(arg0_idx, retval0_idx if retval0_idx is not None else len(header)):
                        if row[i] != "":
                            args.append(row[i])
                if retval0_idx is None:
                    retvals = None
                else:
                    retvals = []
                    for i in range(retval0_idx, len(header)):
                        if row[i] != "":
                            retvals.append(row[i])

                def stringize_typelist(typelist: list[str] | None) -> str:
                    return "none" if typelist is None else ", ".join(typelist)

                result += rf";\{row[name_idx]} {stringize_typelist(args)} -> {stringize_typelist(retvals)}"
                result += "\n"
                result += ";TODO: implement this function"
                result += "\n"
        for name in set(funcs) - set(funcnames_in_funcinfo):
            print(f"warn: function '{name}' is in source code, but not in funcinfo file")
    return cast(Lan22WithFuncrefStr, result)


def resolve_funcref(args, code: Lan22WithFuncrefStr, funcs: dict[str, FuncBody]) -> PureLan22Str:
    result = ""
    for line in code.splitlines(keepends=True):
        ref_match = re.search("(?P<indent> *)@{(?P<func_name>[a-zA-Z0-9_]+)}", line)
        if ref_match is None:
            result += line
            continue
        func_id = funcs[ref_match["func_name"]]["id"]
        for digit in f"{func_id:b}":
            result += ref_match["indent"]
            result += "one\n" if digit == "1" else "zero\n"
    return cast(PureLan22Str, result)


def emit_22lan(args):
    funcs = split_funcs(args)
    for name, body in funcs.items():
        if name == "!!top!!":
            continue
        check_result = check_implementation_exists(body)
        if check_result is None:
            print(f"warn: mismatching startfunc and endfunc in function '{name}'")
        elif check_result == False:
            print(f"warn: function '{name}' doesn't have implementation")

    if any([func["id"] < 0 for func in funcs.values()]):
        code = resolve_autofuncs(args, funcs)
    else:
        with open(args.source, "r", encoding="utf-8") as infile:
            code = cast(Lan22WithFuncrefStr, infile.read())
    with open(args.output, "w", encoding="utf-8") as outfile:
        outfile.write(resolve_funcref(args, code, funcs))


def main():
    parser = argparse.ArgumentParser(description="resolve 22lan's function reference extention", prog="22lan_deref.py")
    parser.add_argument("-s", "--source", help="source file", required=True)
    parser.add_argument("-f", "--funcinfo", help="function information file")
    parser.add_argument("-o", "--output", help="output filename (in result folder)")
    parser.add_argument("-l", "--lang", help="output language", choices=SUFFIXES.keys(), default="22lan")
    parser.add_argument("-d", "--debug", action="store_true", help="enable debug output")
    args = parser.parse_args()

    if args.output is None:
        args.output = Path(args.source).with_suffix(SUFFIXES[args.lang])

    match args.lang:
        case "22lan":
            emit_22lan(args)
        case "funcinfo":
            emit_funcinfo(args)


if __name__ == "__main__":
    main()
