#!/usr/bin/env python3
import sys
import csv

from . import common


class FuncDeclarationSolver:
    code: common.Code

    def __init__(self, args, funcs: dict[str, common.FuncBody]) -> None:
        self.args = args
        self.funcs = funcs
        self.code = common.Code()
        self._resolve_funcdeclarations()

    def _resolve_funcdeclarations(self) -> None:
        if self.args.funcinfo is None:
            print("error: no funcinfo file was supplied", file=sys.stderr)
            sys.exit(1)
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
                        return "none" if typelist is None or len(typelist) == 0 else ", ".join(typelist)

                    result.add_line(
                        rf";\@{row[name_idx]} {stringize_typelist(func_args)} -> {stringize_typelist(retvals)}"
                    )
                    result.add_line("startfunc")
                    result.set_indent("    ")
                    result.add_line(";TODO: implement this function")
                    result.add_line(f"@{{{row[name_idx]}}}")
                    result.set_indent("")
                    result.add_line("endfunc")
                    result.add_line("")
            for name in set(self.funcs) - set(funcnames_in_funcinfo):
                print(f"warn: function '{name}' is in source code, but not in funcinfo file")
        self.code = result
