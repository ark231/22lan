#!/usr/bin/env python3
import re
from base64 import b32encode
from logging import getLogger

logger = getLogger(__name__)

from . import common


class Macro:
    def __init__(self, argnames: list[str]):
        self.argnames: list[str] = argnames
        self.code = common.Code()


def as_macro(dct):
    if "__macro__" in dct:
        result = Macro(dct["argnames"])
        result.code = dct["code"]
        return result
    return dct


def from_macro(macro: Macro):
    return {"__macro__": True, "argnames": macro.argnames, "code": macro.code}


def retrieve_macros(code: common.Code | list[str]) -> tuple[dict[str, Macro], common.Code]:
    current_macro_name = None
    code_without_macro_definition = common.Code()
    macros: dict[str, Macro] = {}
    for line in code:
        match = re.search(r"^ *#defmacro (?P<name>[a-zA-Z0-9_]+)( +(?P<argdecl>.+))?", line)
        if match is not None:
            current_macro_name = match["name"]
            argnames = []
            if match["argdecl"]:
                try:
                    argnames = list(range(int(match["argdecl"])))
                except ValueError:
                    argnames = [argname.strip(" ") for argname in match["argdecl"].split(",")]
            macros[match["name"]] = Macro(argnames)
        elif re.search(r"^ *#endmacro", line) is not None:
            current_macro_name = None
        elif current_macro_name is not None:
            macros[current_macro_name].code.add_line(line)
        else:
            code_without_macro_definition.add_line(line)
    return macros, code_without_macro_definition


def unescape(source: str) -> str:
    source = re.sub(r"(?<!\\)\\n", "\n", source)
    source = re.sub(r"(?<!\\)\\r", "\r", source)
    source = re.sub(r"(?<!\\)\\t", "\t", source)
    source = re.sub(r"(?<!\\)\\0", "\0", source)
    source = re.sub(r"(?<!\\)\\\\", "\\\\", source)
    return source


class MacroResolver:
    def __init__(self, args, code: common.Code, macros: dict[str, Macro]) -> None:
        self.args = args
        self.code = code
        self.macros: dict[str, Macro] = macros

    def _encode_stack_initializer(self, initial_values: bytes) -> str:
        raw_result = b32encode(initial_values).decode("utf-8").rstrip("=")
        prev_char = ""
        count = 0
        result = ""
        for char in raw_result + "\0":  # \0はb32encodeの結果に現れない文字であるため、最後の文字を強制出力させるのにふさわしい
            if char != prev_char:
                if prev_char != "":
                    if count > 6:
                        result += rf"{prev_char}\S{count:o}\E"
                    else:
                        result += f"{prev_char*count}"
                prev_char = char
                count = 1
            else:
                count += 1
        result = result.translate(str.maketrans("01", "OI"))
        return result

    def _expand_macro_recursive(self, code: common.Code) -> common.Code:
        result = common.Code()
        macro_found = False
        for line in code:
            match = re.search(r"^(?P<indent> *)#(?P<name>[a-zA-Z0-9_]+)( +(?P<args>[^;]+))?", line)
            if match:
                macro_found = True
                args = []
                if match["args"]:
                    args = [arg.strip(" ") for arg in match["args"].split(",")]
                if self.args.debug:
                    result.set_indent(match["indent"])
                    result.add_line(f";debug: {line}")
                    result.set_indent("")
                match match["name"]:
                    case "stack":
                        stack_id = int(args[0])
                        value_type = args[1]
                        values = b""
                        match value_type:
                            case "raw":
                                values = bytes(int(value, 0) for value in args[2:])
                            case "cstr":
                                values = unescape(",".join(args[2:])).encode("utf-8") + b"\0"
                            case "intarray":
                                alignment = int(args[2])
                                match args[3].lower():
                                    case "little":
                                        byteorder = "little"
                                    case "big":
                                        byteorder = "big"
                                    case _:
                                        logger.error("unknown byteorder %s", args[3])
                                        result.add_line(f"!!!!!!!error!!!!!!! {line}")
                                        continue
                                values = b""
                                for raw_value in args[4:]:
                                    value_match = re.search(r"(?P<value>\d+):(?P<repeat>\d+)", raw_value)
                                    if value_match:
                                        value = int(value_match["value"], 0)
                                        repeat = int(value_match["repeat"], 0)
                                    else:
                                        value = int(raw_value, 0)
                                        repeat = 1
                                    values += value.to_bytes(alignment // 8, byteorder) * repeat
                            case _:
                                logger.error('unknown value type "%s"', value_type)
                                result.add_line(f"!!!!!!!error!!!!!!! {line}")
                        result.set_indent(match["indent"])
                        result.add_line(rf"\{'OI2'[stack_id]}{self._encode_stack_initializer(values)}")
                        result.set_indent("")
                    case _:
                        for macro_line in self.macros[match["name"]].code:
                            for arg_placeholder in re.findall(r"#{(?P<name>[^}]+)}", macro_line):
                                if arg_placeholder == "__VA_ARGS__":
                                    actual_args = args[self.macros[match["name"]].argnames.index("...") :]
                                else:
                                    actual_args = [args[self.macros[match["name"]].argnames.index(arg_placeholder)]]
                                macro_line = re.sub(
                                    f"#{{{arg_placeholder}}}",
                                    f"{','.join(actual_args)}",
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
