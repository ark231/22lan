#!/usr/bin/env python3

import argparse
from pathlib import Path
import csv
import re
from langs import lan22_annotation, base
from typing import cast
import io
from pprint import pprint


def main():
    parser = argparse.ArgumentParser(description="resolve 22lan's function reference extention", prog="22lan_deref.py")
    parser.add_argument("-s", "--source", help="source file", required=True)
    parser.add_argument("-o", "--output", help="output filename (in result folder)")
    parser.add_argument("-d", "--debug", action="store_true", help="enable debug output")
    args = parser.parse_args()

    if args.output is None:
        args.output = Path(args.source).with_suffix(".22l")

    escaped = ""
    with open(args.source, "r", encoding="utf-8") as infile:
        for line in infile:
            escaped += re.sub("(@{(?P<func_name>[a-zA-Z0-9_]+)})", r";\1", line)
    generator = lan22_annotation.FuncInfoTableGenerator()
    generator.from_tree(base.Lan22Parser.parse(escaped))
    funcs: dict[str, dict[str, int | list[str]]] = {}
    for func in generator.retrieved_funcs:
        funcs[cast(str, func["name"])] = {
            "id": int(func["id"], base=0),
            "args": func["args"],
            "retvals": func["retvals"],
        }
    # with open(args.func_info, "r", encoding="utf-8", newline="") as func_info_file:
    #     reader = csv.reader(func_info_file)
    #     header = next(reader)
    #     col_name = header.index("name")
    #     col_id = header.index("id")
    #     funcs: dict[str, int] = {}
    #     for row in reader:
    #         funcs[row[col_name]] = int(row[col_id], base=0)
    with open(args.source, "r", encoding="utf-8") as infile, open(args.output, "w", encoding="utf-8") as outfile:
        for line in infile:
            ref_match = re.search("(?P<indent> *)@{(?P<func_name>[a-zA-Z0-9_]+)}", line)
            if ref_match is None:
                outfile.write(line)
                continue
            func_id = funcs[ref_match["func_name"]]["id"]
            for digit in f"{func_id:b}":
                outfile.write(ref_match["indent"])
                outfile.write("one\n" if digit == "1" else "zero\n")


if __name__ == "__main__":
    main()
