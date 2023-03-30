#!/usr/bin/env python3
import argparse
from pathlib import Path
from langs import lan22_nyulan, lan22_cxx, lan22_annotation, base
from typing import Final
from logging import getLogger, config
import toml

logger = getLogger(__name__)

SUFFIXES: Final[dict[str, str]] = {"nyulan": ".nyu", "cxx": ".cpp", "annotation": ".csv"}


def main() -> None:
    parser = argparse.ArgumentParser(description="convert 22lan source code to specified language", prog="22lan.py")
    parser.add_argument("-s", "--source", help="source file", required=True, nargs="+")
    parser.add_argument("-o", "--output", help="output filename (in result folder)")
    parser.add_argument("-l", "--lang", help="output language", choices=SUFFIXES.keys(), default="nyulan")
    parser.add_argument("-d", "--debug", help="enable debug output", type=int, default=0)
    parser.add_argument("--Xbackend", action="append", help="similar to gcc's -Xlinker")
    args = parser.parse_args()

    if args.output is None:
        # args.output = Path(args.source).with_suffix(SUFFIXES[args.lang])
        args.output = Path("a").with_suffix(SUFFIXES[args.lang])

    match args.lang:
        case "nyulan":
            Generator = lan22_nyulan.NyulanGenerator
        case "cxx":
            Generator = lan22_cxx.CPlusPlusGenerator
        case "annotation":
            Generator = lan22_annotation.FuncInfoTableGenerator
        case _:
            Generator = lan22_nyulan.NyulanGenerator

    concatenated_source = ""
    for source in args.source:
        with open(source, "r", encoding="utf8") as sourcefile:
            concatenated_source += sourcefile.read()
            concatenated_source += "\n"

    parsed_data = base.Lan22Parser.parse(concatenated_source)
    generator = Generator(debug_level=args.debug, backend_specific_args=args.Xbackend)
    try:
        generator.from_tree(parsed_data)
    except base.ParseError as e:
        logger.error("parse error at %s:%d info:%s", args.source, e.linenum, e)

    if args.debug >= 1:
        print(generator)

    with open(args.output, "w", encoding="utf8") as outfile:
        generator.dump(outfile)


if __name__ == "__main__":
    config.dictConfig(toml.load(Path(__file__).parent / "log_config.toml"))
    main()
