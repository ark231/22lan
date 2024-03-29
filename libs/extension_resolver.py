#!/usr/bin/env python3
import sys
import csv
import math
import sympy
from sympy.parsing import sympy_parser
import re
import json
from logging import getLogger

logger = getLogger(__name__)

from . import common
from .macro_resolver import MacroResolver, retrieve_macros, as_macro, Macro


class ExtensionResolver:
    def __init__(self, args, funcs: dict[str, common.FuncBody]) -> None:
        self.args = args
        self.funcs = funcs
        self.code = common.Code()
        self.labels: dict[int, dict[str, int]] = {}
        self.macros: dict[str, Macro] = {}
        if any([func["id"] < 0 for func in funcs.values()]):
            self.code = common.Code()
            self._resolve_autofuncs()
        else:
            with open(args.source, "r", encoding="utf-8") as infile:
                self.code = common.Code(infile.read())

        def decode_lib(dct):
            result = as_macro(dct)
            if isinstance(result, dict):
                result = common.Code.as_code(result)
            return result

        if self.args.external is not None:
            for external_funcinfo_file in self.args.external:
                with open(external_funcinfo_file, "r", encoding="utf-8") as infile:
                    external = json.load(infile, object_hook=decode_lib)
                for fname, fid in external["funcs"].items():
                    self.funcs[fname] = common.FuncBody(id=fid, content="")
                self.macros |= external["macros"]

    def _resolve_autofuncs(self) -> None:
        result = common.Code(self.funcs["!!top!!"]["content"])
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
                            logger.error("unknown functype '%s' for func '%s'", row[type_idx], row[name_idx])
                            logger.error("func_id from_annotation: %d, from funcinfo file: %d", func["id"], row[id_idx])
                            sys.exit(1)
                    result.add_lines(func["content"].splitlines())
                    funcnames_in_funcinfo.append(row[name_idx])
                except KeyError:
                    logger.warning(
                        "func '%s is in funcinfo file, but not in source code, thus not implemented'", row[name_idx]
                    )
                    match row[type_idx]:
                        case "std":
                            full_id = int(f"0b11{int(row[id_idx],0):b}", 0)
                        case "usr":
                            full_id = int(f"0b10{int(row[id_idx],0):b}", 0)
                        case "raw":
                            full_id = int(row[id_idx], 0)
                        case _:
                            logger.error("unknown functype '%s' for func '%s'", row[type_idx], row[name_idx])
                            logger.error("from funcinfo file: %d", row[id_idx])
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
                    self.funcs[row[name_idx]] = common.FuncBody(id=full_id, content="")
            for name in set(self.funcs) - set(funcnames_in_funcinfo):
                logger.warning("function '%s' is in source code, but not in funcinfo file", name)
        self.code = result

    def _mangle_label(self, func_index: int, name: str):
        return f"__F{func_index}L_{name}"

    def resolve_pseudo_ops(self) -> None:
        result = common.Code()
        current_func_index = 0
        current_autolabel_id = 0

        for line in self.code:
            operation_match = re.search(r"(?P<indent> *)(?P<op>[a-z0-9_]+)", line)
            pseudo_match = re.search(r"^(?P<indent> *)\\(?P<pseudo_op>[a-zA-Z0-9_]+) +(?P<pseudo_arg>[^;]+)", line)
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
                result.add_line(f"${{{pseudo_match['pseudo_arg']}:8}}")
                result.add_line("pushl8")
            elif pseudo_match["pseudo_op"] == "pushl64":
                result.add_line(f"${{{pseudo_match['pseudo_arg']}:64}}")
                for _ in range(8):
                    result.add_line("pushl8")
            elif pseudo_match["pseudo_op"] == "autolabel":
                labelname_match = re.search(r"(?P<name>[a-zA-Z0-9_]+)", pseudo_match["pseudo_arg"])
                if labelname_match is None:
                    logger.error("no labelname at autolabel pseudo_op")
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
            elif pseudo_match["pseudo_op"] == "autoliteral":
                reflabel_pattern = r"l{(?P<name>[a-zA-Z0-9_]+)}"
                expr = pseudo_match["pseudo_arg"]
                for labelname in set(re.findall(reflabel_pattern, expr)):
                    expr = re.sub(f"l{{{labelname}}}", self._mangle_label(current_func_index, labelname), expr)
                result.add_line(f"%autoliteral {expr}")
            else:
                logger.error('unknown pseudo operation "%s"', pseudo_match["pseudo_op"])
                result.add_line(f"!!!!!!!error!!!!!!! '{line}'")
            if self.args.debug:
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
        result = common.Code()
        current_func_index = 1
        for line in self.code:
            operation_match = re.search(r"(?P<indent> *)(?P<op>[a-z0-9_]+)", line)
            pseudo_match = re.search(r"(?P<indent> *)%(?P<pseudo_op>[a-zA-Z0-9_]+) +(?P<pseudo_arg>[^;]+)", line)
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
                if size >= 2:
                    result.add_line("xchg13")  # restore r1 from r3
            elif pseudo_match["pseudo_op"] == "autoliteral":
                value = self.eval(pseudo_match["pseudo_arg"])
                result.add_line(f"${{{value}}}")
            else:
                logger.error('unknown dependant pseudo operation "%s"', pseudo_match["pseudo_op"])
                result.add_line(f"!!!!!!!error!!!!!!! '{line}'")
            result.set_indent("")
        self.code = result

    def resolve_callfunc(self, indent: str, pseudo_arg: str) -> common.Code:
        result = common.Code()
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
            result.add_line("pop8s1")
        result.add_line("call")
        return result

    def resolve_funcref(self) -> None:
        result = common.Code()
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
        result = common.Code()
        for line in self.code:
            VALUE_PATTERN = r"(?P<number>[-+xob_0-9]+)( *: *(?P<bitwidth>[0-9]+))?"
            literal_match = re.search(rf"(?P<indent> *)\${{ *{VALUE_PATTERN} *}}", line)
            if literal_match is None:
                result.add_line(line)
                continue
            result.set_indent(literal_match["indent"])
            value = int(literal_match["number"], 0)
            if literal_match["bitwidth"]:
                bitwidth = int(literal_match["bitwidth"])
            else:
                bitwidth = 64
            if value >= 0:
                binary = f"{value:b}"
                if len(binary) > bitwidth:
                    logger.error("number %d cannot be expressed with %d bit unsigned integer", value, bitwidth)
                    result.add_line(f"!!!!!!!error!!!!!!! {line}")
                else:
                    for digit in binary:
                        result.add_line("one" if digit == "1" else "zero")
            else:
                for digit in f"{2**bitwidth - abs(value):b}":
                    result.add_line("one" if digit == "1" else "zero")
            result.set_indent("")
        self.code = result

    def resolve_macro(self) -> None:
        macros, code = retrieve_macros(self.code)
        self.macros |= macros
        resolver = MacroResolver(self.args, code, self.macros)
        resolver.expand_macro()
        self.code = resolver.code

    def resolve_all(self) -> None:
        self.resolve_macro()
        self.resolve_pseudo_ops()
        self.resolve_dependant_pseudo_ops()
        self.resolve_funcref()
        self.resolve_literal()
