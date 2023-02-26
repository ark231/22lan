#!/usr/bin/env python3

from . import common
import re


class Macro:
    def __init__(self, argnames: list[str]):
        self.argnames: list[str] = argnames
        self.code = common.Code()


class MacroResolver:
    def __init__(self, args, code: common.Code) -> None:
        self.args = args
        self.code = code
        self.macros: dict[str, Macro] = {}
        self._retrieve_macros()

    def _retrieve_macros(self) -> None:
        current_macro_name = None
        code_without_macro_definition = common.Code()
        for line in self.code:
            match = re.search(r"^ *#defmacro (?P<name>[a-zA-Z0-9_]+) +(?P<argdecl>.+)?", line)
            if match is not None:
                current_macro_name = match["name"]
                argnames = []
                if match["argdecl"]:
                    try:
                        argnames = list(range(int(match["argdecl"])))
                    except ValueError:
                        argnames = [argname.strip(" ") for argname in match["argdecl"].split(",")]
                self.macros[match["name"]] = Macro(argnames)
            elif re.search(r"^ *#endmacro", line) is not None:
                current_macro_name = None
            elif current_macro_name is not None:
                self.macros[current_macro_name].code.add_line(line)
            else:
                code_without_macro_definition.add_line(line)
        self.code = code_without_macro_definition

    def _expand_macro_recursive(self, code: common.Code) -> common.Code:
        result = common.Code()
        macro_found = False
        for line in code:
            match = re.search(r"^(?P<indent> *)#(?P<name>[a-zA-Z0-9_]+) +(?P<args>.+)?", line)
            if match:
                macro_found = True
                args = []
                if match["args"]:
                    args = [arg.strip(" ") for arg in match["args"].split(",")]
                if self.args.debug:
                    result.set_indent(match["indent"])
                    result.add_line(f";debug: {line}")
                    result.set_indent("")
                for macro_line in self.macros[match["name"]].code:
                    for arg_placeholder in re.findall(r"#{(?P<name>[^}]+)}", macro_line):
                        macro_line = re.sub(
                            f"#{{{arg_placeholder}}}",
                            f"{args[self.macros[match['name']].argnames.index(arg_placeholder)]}",
                            macro_line,
                        )
                    result.add_line(macro_line)
                if self.args.debug:
                    result.set_indent(match["indent"])
                    result.add_line(";debug: end macro")
                    result.set_indent("")
            else:
                result.add_line(line)
        if not macro_found:
            return result
        else:
            return self._expand_macro_recursive(result)

    def expand_macro(self) -> None:
        self.code = self._expand_macro_recursive(self.code)
