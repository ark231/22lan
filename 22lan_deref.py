#!/usr/bin/env python3

import sys
import argparse
from pathlib import Path
import csv
import re
from typing import cast, Final, ClassVar, TypedDict, NewType, TypeVar, Generic, Literal
import io
from enum import Enum, auto
from lark.lexer import Token
import math
import sympy
from sympy.parsing import sympy_parser

from langs import lan22_annotation, base

SUFFIXES: Final[dict[str, str]] = {"22lan": ".22l", "funcinfo": ".ext.csv", "22lan_extended": ".22le"}


class ExtendedAnnotationParser(lan22_annotation.AnnotationParser):
    larkfile: ClassVar[Path] = Path(__file__).parent / "langs" / "extended_annotation.lark"


AUTOFUNC_STD_PATTERN = r";\\autofunc +std"
AUTOFUNC_USR_PATTERN = r";\\autofunc +usr"


def escape_extensions(filename: str, funcref=True, autofunc=True, pseudo_ops=True) -> str:
    escaped = ""
    with open(filename, "r", encoding="utf-8") as infile:
        for line in infile:
            if funcref:
                line = re.sub("(@{(?P<func_name>[a-zA-Z0-9_]+)})", r";\1", line)
            if autofunc:
                line = re.sub(AUTOFUNC_STD_PATTERN, r";\\func -0b1", line)
                line = re.sub(AUTOFUNC_USR_PATTERN, r";\\func -0b10", line)
            if pseudo_ops:
                line = re.sub(r"( *)(\\.*)", r";\1\2", line)
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
    escaped = escape_extensions(args.source, funcref=False, pseudo_ops=False)
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


ExtendedLan22Str = NewType("ExtendedLan22Str", str)
PureLan22Str = NewType("PureLan22Str", str)


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


class ExtensionResolver:
    def __init__(self, args, funcs: dict[str, FuncBody]) -> None:
        self.args = args
        self.funcs = funcs
        self.code = Code()
        self.labels: dict[int, dict[str, int]] = {}
        if any([func["id"] < 0 for func in funcs.values()]):
            self.code = Code()
            self._resolve_autofuncs()
        else:
            with open(args.source, "r", encoding="utf-8") as infile:
                self.code = Code(infile.read())

    def _resolve_autofuncs(self) -> None:
        if self.args.funcinfo is None:
            print("error: source file contains autofunc, but no funcinfo file was supplied", file=sys.stderr)
            sys.exit(1)
        result = Code(self.funcs["!!top!!"]["content"])
        del self.funcs["!!top!!"]
        funcnames_in_funcinfo: list[str] = []
        with open(self.args.funcinfo, "r", encoding="utf-8") as infile:
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
                    func = self.funcs[row[name_idx]]
                    match row[type_idx]:
                        case "raw":
                            result.add_line(rf";\func {int(row[id_idx],0):#b}")
                            self.funcs[row[name_idx]]["id"] = int(row[id_idx], 0)
                        case "std":
                            result.add_line(rf";\func 0b11{int(row[id_idx],0):b}")
                            self.funcs[row[name_idx]]["id"] = int(f"0b11{int(row[id_idx],0):b}", 2)
                        case "usr":
                            result.add_line(rf";\func 0b10{int(row[id_idx],0):b}")
                            self.funcs[row[name_idx]]["id"] = int(f"0b10{int(row[id_idx],0):b}", 2)
                        case _:
                            print(f"error: unknown functype '{row[type_idx]}' for func '{row[name_idx]}'")
                            print(rf"func_id from_annotation: {func['id']}, from funcinfo file: {row[id_idx]}")
                            sys.exit(1)
                    result.add_lines(func["content"].splitlines())
                    funcnames_in_funcinfo.append(row[name_idx])
                except KeyError:
                    print(
                        f"warn: func '{row[name_idx]} is in funcinfo file, but not in source code, thus not implemented'"
                    )
                    match row[type_idx]:
                        case "std":
                            full_id = int(f"0b11{int(row[id_idx],0):b}", 0)
                        case "usr":
                            full_id = int(f"0b10{int(row[id_idx],0):b}", 0)
                        case "raw":
                            full_id = int(row[id_idx], 0)
                        case _:
                            print(f"error: unknown functype '{row[type_idx]}' for func '{row[name_idx]}'")
                            print(rf"func_id from funcinfo file: {row[id_idx]}")
                            sys.exit(1)
                    result.add_line(rf";\func {full_id:#b}")
                    if arg0_idx is None:
                        func_args = None
                    else:
                        func_args = []
                        for i in range(arg0_idx, retval0_idx if retval0_idx is not None else len(header)):
                            if row[i] != "":
                                func_args.append(row[i])
                    if retval0_idx is None:
                        retvals = None
                    else:
                        retvals = []
                        for i in range(retval0_idx, len(header)):
                            if row[i] != "":
                                retvals.append(row[i])

                    def stringize_typelist(typelist: list[str] | None) -> str:
                        return "none" if typelist is None else ", ".join(typelist)

                    result.add_line(
                        rf";\{row[name_idx]} {stringize_typelist(func_args)} -> {stringize_typelist(retvals)}"
                    )
                    result.add_line(";TODO: implement this function")
                    self.funcs[row[name_idx]] = FuncBody(id=full_id, content="")
            for name in set(self.funcs) - set(funcnames_in_funcinfo):
                print(f"warn: function '{name}' is in source code, but not in funcinfo file")
        self.code = result

    def _mangle_label(self, func_index: int, name: str):
        return f"__F{func_index}L_{name}"

    def resolve_pseudo_ops(self) -> None:
        result = Code()
        current_func_index = 0
        current_autolabel_id = 0

        for line in self.code:
            operation_match = re.search(r"(?P<indent> *)(?P<op>[a-z0-9_]+)", line)
            pseudo_match = re.search(r"^(?P<indent> *)\\(?P<pseudo_op>[a-zA-Z0-9_]+) +(?P<pseudo_arg>.+)", line)
            if operation_match is not None:
                if operation_match["op"] == "startfunc":
                    self.labels[current_func_index] = {}
                elif operation_match["op"] == "endfunc":
                    current_func_index += 1
                    current_autolabel_id = 0
            if pseudo_match is None:
                result.add_line(line)
                continue
            result.set_indent(pseudo_match["indent"])
            if self.args.debug:
                result.add_line(f";debug: {line.strip(' ')}")
            if pseudo_match["pseudo_op"] == "func":
                result.add_line(line)
            elif pseudo_match["pseudo_op"] == "call":
                result += self.resolve_callfunc(pseudo_match["indent"], pseudo_match["pseudo_arg"])
            elif pseudo_match["pseudo_op"] == "pushl8":
                result.add_line(f"${{{pseudo_match['pseudo_arg']}}}")
                result.add_line("pushl8")
            elif pseudo_match["pseudo_op"] == "autolabel":
                labelname_match = re.search(r"(?P<name>[a-zA-Z0-9_]+)", pseudo_match["pseudo_arg"])
                if labelname_match is None:
                    print("error: no labelname at autolabel pseudo_op")
                    result.add_line(f"!!!!!!!error!!!!!!! {line}")
                    continue
                result.add_line(f"${{{current_autolabel_id}}}")
                result.add_line("deflabel")
                self.labels[current_func_index][labelname_match["name"]] = current_autolabel_id
                current_autolabel_id += 1
            elif pseudo_match["pseudo_op"] == "autopushltor0":
                reflabel_pattern = r"l{(?P<name>[a-zA-Z0-9_]+)}"
                expr = pseudo_match["pseudo_arg"]
                for labelname in set(re.findall(reflabel_pattern, expr)):
                    expr = re.sub(f"l{{{labelname}}}", self._mangle_label(current_func_index, labelname), expr)
                result.add_line(f"%autopushltor0 {expr}")
            else:
                print(f'error: unknown pseudo operation "{pseudo_match["pseudo_op"]}"')
                result.add_line(f"!!!!!!!error!!!!!!! '{line}'")
            result.add_line(";debug: end pseudo operation")
            result.set_indent("")
        self.code = result

    def eval(self, expr: str) -> int:
        result = 0
        parsed_expr = sympy_parser.parse_expr(expr)
        replacements = []
        for func_index, labels in self.labels.items():
            for name, value in labels.items():
                mangled_label_name = f"__F{func_index}L_{name}"
                replacements.append((sympy.Symbol(mangled_label_name), value))
        result = int(parsed_expr.subs(replacements))
        return result

    def resolve_dependant_pseudo_ops(self) -> None:
        result = Code()
        current_func_index = 1
        for line in self.code:
            operation_match = re.search(r"(?P<indent> *)(?P<op>[a-z0-9_]+)", line)
            pseudo_match = re.search(r"(?P<indent> *)%(?P<pseudo_op>[a-zA-Z0-9_]+) +(?P<pseudo_arg>.+)", line)
            if operation_match is not None:
                if operation_match["op"] == "endfunc":
                    current_func_index += 1
            if pseudo_match is None:
                result.add_line(line)
                continue
            result.set_indent(pseudo_match["indent"])
            if pseudo_match["pseudo_op"] == "autopushltor0":
                value = self.eval(pseudo_match["pseudo_arg"])
                size = math.ceil(len(f"{value:b}") / 8)
                value = list(value.to_bytes(size, "big"))
                if size >= 2:
                    result.add_line("xchg13")  # save r1 to r3
                    # load 8 to r1_8
                    result.add_line("${8}")
                    result.add_line("pushl8")
                    result.add_line("pop8s0")
                    result.add_line("xchg03")
                    result.add_line("xchg13")
                    result.add_line("xchg03")

                is_first = True
                for byte in value:
                    if not is_first:
                        result.add_line("lshift")
                        result.add_line("xchg23")
                        result.add_line("xchg03")
                        result.add_line("xchg23")
                    else:
                        is_first = False

                    result.add_line(f"${{{byte}}}")
                    result.add_line("pushl8")
                    result.add_line("pop8s0")
                result.add_line("xchg13")  # restore r1 from r3
            else:
                print(f'error: unknown dependant pseudo operation "{pseudo_match["pseudo_op"]}"')
                result.add_line(f"!!!!!!!error!!!!!!! '{line}'")
            result.set_indent("")
        self.code = result

    def resolve_callfunc(self, indent: str, pseudo_arg: str) -> Code:
        result = Code()
        result.set_indent(indent)
        func_name = pseudo_arg.replace(" ", "")
        result.add_line(f"@{{{func_name}}}")
        func_id = self.funcs[func_name]["id"]
        num_shift = math.floor(len(f"{func_id:b}") / 8)
        result.add_line("pushl8")
        result.add_line("pop8s0")
        if num_shift != 0:
            result.add_line("push8s1")
            result.add_line("xchg13")
            result.add_line("xchg03")
            result.add_line("${8}")
            result.add_line("pop8s0")
            result.add_line("xchg03")
            result.add_line("xchg13")
            for _ in range(num_shift):
                result.add_line("lshift")
                result.add_line("xchg23")
                result.add_line("xchg03")
                result.add_line("pushl8")
                result.add_line("pop8s0")
        result.add_line("call")
        return result

    def resolve_funcref(self) -> None:
        result = Code()
        for line in self.code:
            ref_match = re.search("(?P<indent> *)@{(?P<func_name>[a-zA-Z0-9_]+)}", line)
            if ref_match is None:
                result.add_line(line)
                continue
            func_id = self.funcs[ref_match["func_name"]]["id"]
            result.set_indent(ref_match["indent"])
            result.add_line(f"${{{func_id}}}")
            result.set_indent("")
        self.code = result

    def resolve_literal(self) -> None:
        result = Code()
        for line in self.code:
            literal_match = re.search(r"(?P<indent> *)\${(?P<value>.+)}", line)
            if literal_match is None:
                result.add_line(line)
                continue
            result.set_indent(literal_match["indent"])
            value = int(literal_match["value"], 0)
            for digit in f"{value:b}":
                result.add_line("one" if digit == "1" else "zero")
            result.set_indent("")
        self.code = result

    def resolve_all(self) -> None:
        self.resolve_pseudo_ops()
        self.resolve_dependant_pseudo_ops()
        self.resolve_funcref()
        self.resolve_literal()


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
    resolver = ExtensionResolver(args, funcs)

    with open(args.output, "w", encoding="utf-8") as outfile:
        resolver.resolve_all()
        outfile.write(resolver.code.as_str())


class FuncDeclarationSolver:
    code: Code

    def __init__(self, args, funcs: dict[str, FuncBody]) -> None:
        self.args = args
        self.funcs = funcs
        self.code = Code()
        self._resolve_funcdeclarations()

    def _resolve_funcdeclarations(self) -> None:
        if self.args.funcinfo is None:
            print("error: no funcinfo file was supplied", file=sys.stderr)
            sys.exit(1)
        result = Code(self.funcs["!!top!!"]["content"])
        del self.funcs["!!top!!"]
        funcnames_in_funcinfo: list[str] = []
        with open(self.args.funcinfo, "r", encoding="utf-8") as infile:
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
                    func = self.funcs[row[name_idx]]
                    match row[type_idx]:
                        case "raw":
                            result.add_line(rf";\func {int(row[id_idx],0):#b}")
                        case "std" | "usr":
                            result.add_line(rf";\autofunc {row[type_idx]}")
                        case _:
                            print(f"error: unknown functype '{row[type_idx]}' for func '{row[name_idx]}'")
                            print(rf"func_id from_annotation: {func['id']}, from funcinfo file: {row[id_idx]}")
                            sys.exit(1)
                    result.add_lines(func["content"].splitlines())
                    funcnames_in_funcinfo.append(row[name_idx])
                except KeyError:
                    print(
                        f"warn: func '{row[name_idx]} is in funcinfo file, but not in source code, thus not implemented'"
                    )
                    match row[type_idx]:
                        case "std" | "usr":
                            result.add_line(rf";\autofunc {row[type_idx]}")
                        case "raw":
                            result.add_line(rf";\func {int(row[id_idx],0):#b}")
                        case _:
                            print(f"error: unknown functype '{row[type_idx]}' for func '{row[name_idx]}'")
                            print(rf"func_id from funcinfo file: {row[id_idx]}")
                            sys.exit(1)
                    if arg0_idx is None:
                        func_args = None
                    else:
                        func_args = []
                        for i in range(arg0_idx, retval0_idx if retval0_idx is not None else len(header)):
                            if row[i] != "":
                                func_args.append(row[i])
                    if retval0_idx is None:
                        retvals = None
                    else:
                        retvals = []
                        for i in range(retval0_idx, len(header)):
                            if row[i] != "":
                                retvals.append(row[i])

                    def stringize_typelist(typelist: list[str] | None) -> str:
                        return "none" if typelist is None else ", ".join(typelist)

                    result.add_line(
                        rf";\{row[name_idx]} {stringize_typelist(func_args)} -> {stringize_typelist(retvals)}"
                    )
                    result.add_line(";TODO: implement this function")
            for name in set(self.funcs) - set(funcnames_in_funcinfo):
                print(f"warn: function '{name}' is in source code, but not in funcinfo file")
        self.code = result


def emit_22lan_extended(args):
    funcs = split_funcs(args)
    for name, body in funcs.items():
        if name == "!!top!!":
            continue
        check_result = check_implementation_exists(body)
        if check_result is None:
            print(f"warn: mismatching startfunc and endfunc in function '{name}'")
        elif check_result == False:
            print(f"warn: function '{name}' doesn't have implementation")
    resolver = FuncDeclarationSolver(args, funcs)

    with open(args.output, "w", encoding="utf-8") as outfile:
        outfile.write(resolver.code.as_str())


def main():
    parser = argparse.ArgumentParser(
        description="resolve 22lan's function reference extention",
        prog="22lan_deref.py",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("-s", "--source", help="source file", required=True)
    parser.add_argument("-f", "--funcinfo", help="function information file")
    parser.add_argument("-o", "--output", help="output filename (in result folder)")
    parser.add_argument("-l", "--lang", help="output language", choices=SUFFIXES.keys(), default="22lan")
    parser.add_argument("-d", "--debug", action="store_true", help="enable debug output")
    args = parser.parse_args()

    if args.output is None:
        args.output = Path(args.source).with_suffix(SUFFIXES[args.lang])
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


if __name__ == "__main__":
    main()
