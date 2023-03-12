#!/usr/bin/env python3

import argparse
import re
import csv


class FuncNameDemangler:
    def __init__(self, filenames: list[str]):
        func_id_to_name: dict[int, str] = {}
        for filename in filenames:
            with open(filename, "r", encoding="utf8") as infile:
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
                    func_id_to_name[func_id] = func_name
        self.func_id_to_name = func_id_to_name

    def demangle(self, mangled_funcname: str) -> str:
        id_match = re.match(r"f(?P<id>[01]+)", mangled_funcname)
        if id_match is None:
            return mangled_funcname
        retrieved_id = int(id_match["id"], 2)
        if retrieved_id not in self.func_id_to_name:
            return mangled_funcname
        return self.func_id_to_name[retrieved_id]


def main():
    parser = argparse.ArgumentParser(
        description="parse 22lan debug log",
        prog="parse_debuglog.py",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("-s", "--source", help="source file", required=True)
    parser.add_argument("-o", "--output", help="output filename (in result folder)", required=True)
    parser.add_argument("-f", "--funcinfo", help="function information files", nargs="*", default=[])
    parser.add_argument("--suppress-operations", action="store_true")
    args = parser.parse_args()

    demangler = FuncNameDemangler(args.funcinfo)

    with open(args.source, "r", encoding="utf8") as infile, open(args.output, "w", encoding="utf8") as outfile:
        callstack = []
        indent = "    "
        show_state = False
        previous_state = ""
        previous_state_s0 = ""
        previous_state_s1 = ""
        previous_state_s2 = ""
        for line in infile:
            match_start = re.search(r";start (?P<fname>[a-zA-Z0-9_]+)", line)
            match_end = re.search(r";end (?P<fname>[a-zA-Z0-9_]+)", line)
            match_state = re.search(r" *r0:.*", line)
            match_state_s0 = re.search(r" *s0:.*", line)
            match_state_s1 = re.search(r" *s1:.*", line)
            match_state_s2 = re.search(r" *s2:.*", line)
            match_exit = re.search(r" *exit", line)
            if match_start is not None:
                if previous_state != "":
                    outfile.write("\n")
                    outfile.write(f"{indent*len(callstack)}{previous_state.lstrip(' ')}")
                if previous_state_s0 != "":
                    outfile.write(f"{indent*len(callstack)}{previous_state_s0.lstrip(' ')}")
                if previous_state_s1 != "":
                    outfile.write(f"{indent*len(callstack)}{previous_state_s1.lstrip(' ')}")
                if previous_state_s2 != "":
                    outfile.write(f"{indent*len(callstack)}{previous_state_s2.lstrip(' ')}")
                demangled_fname = demangler.demangle(match_start["fname"])
                outfile.write(f"{indent*len(callstack)}{line.replace(match_start['fname'],demangled_fname)}")
                callstack.append(demangled_fname)
                show_state = False
            elif match_end is not None:
                callstack.pop()
                outfile.write(
                    f"{indent*len(callstack)}{line.replace(match_end['fname'],demangler.demangle(match_end['fname']))}"
                )
                if len(callstack) != 0:
                    outfile.write(f"{indent*len(callstack)};now in {callstack[-1]}\n")
                show_state = True
            elif match_state is not None:
                previous_state = line
                if not args.suppress_operations or show_state:
                    outfile.write(f"{indent*len(callstack)}{line.lstrip(' ')}")
            elif match_state_s0 is not None:
                previous_state_s0 = line
                if not args.suppress_operations or show_state:
                    outfile.write(f"{indent*len(callstack)}{line.lstrip(' ')}")
            elif match_state_s1 is not None:
                previous_state_s1 = line
                if not args.suppress_operations or show_state:
                    outfile.write(f"{indent*len(callstack)}{line.lstrip(' ')}")
            elif match_state_s2 is not None:
                previous_state_s2 = line
                if not args.suppress_operations or show_state:
                    outfile.write(f"{indent*len(callstack)}{line.lstrip(' ')}")
            else:
                show_state = False
                if not (args.suppress_operations and match_exit is None):
                    outfile.write(f"{indent*len(callstack)}{line.lstrip(' ')}")


if __name__ == "__main__":
    main()
