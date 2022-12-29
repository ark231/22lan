#!/usr/bin/env python3
import argparse
from pathlib import Path
import sys
from langs import lan22_nyulan, lan22_cxx, lan22_annotation, base
from typing import Final

SUFFIXES: Final[dict[str, str]] = {"nyulan": ".nyu", "cxx": ".cpp", "annotation": ".csv"}


def main() -> None:
    parser = argparse.ArgumentParser(description="convert 22lan source code to specified language", prog="22lan.py")
    parser.add_argument("-s", "--source", help="source file", required=True)
    parser.add_argument("-o", "--output", help="output filename (in result folder)")
    parser.add_argument("-l", "--lang", help="output language", choices=SUFFIXES.keys(), default="nyulan")
    parser.add_argument("-d", "--debug", action="store_true", help="enable debug output")
    args = parser.parse_args()

    if args.output is None:
        args.output = Path(args.source).with_suffix(SUFFIXES[args.lang])

    match args.lang:
        case "nyulan":
            Generator = lan22_nyulan.NyulanGenerator
        case "cxx":
            Generator = lan22_cxx.CPlusPlusGenerator
        case "annotation":
            Generator = lan22_annotation.FuncInfoTableGenerator
        case _:
            Generator = lan22_nyulan.NyulanGenerator

    with open(args.source, "r", encoding="utf8") as sourcefile:
        parsed_data = base.Lan22Parser.parse(sourcefile.read())
    generator = Generator()
    try:
        generator.from_tree(parsed_data)
    except base.ParseError as e:
        print(sys.stderr, f"parse error at {args.source}:{e.linenum} info:{e}")

    if args.debug:
        print(generator)

    with open(args.output, "w", encoding="utf8") as outfile:
        generator.dump(outfile)


if __name__ == "__main__":
    main()
