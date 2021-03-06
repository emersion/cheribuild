#
# Copyright (c) 2016 Alex Richardson
# All rights reserved.
#
# This software was developed by SRI International and the University of
# Cambridge Computer Laboratory under DARPA/AFRL contract FA8750-10-C-0237
# ("CTSRD"), as part of the DARPA CRASH research programme.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE AUTHOR AND CONTRIBUTORS ``AS IS'' AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED.  IN NO EVENT SHALL THE AUTHOR OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS
# OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
# HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY
# OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF
# SUCH DAMAGE.
#
import argparse
import json
import os
import shlex
import shutil
import sys
import collections.abc

try:
    import argcomplete
except ImportError:
    argcomplete = None

from ..colour import *
from ..utils import typing, Type_T, fatalError
from pathlib import Path


class ComputedDefaultValue(object):
    def __init__(self, function: "typing.Callable[[CheriConfig, typing.Any], typing.Any]",
                 asString: "typing.Union[str, typing.Callable[[typing.Any], str]"):
        self.function = function
        self.asString = asString

    def __call__(self, config: "CheriConfig", cls):
        return self.function(config, cls)

    # def __str__(self):
    #     return self.asString

# From https://bugs.python.org/issue25061
class _EnumArgparseType(object):
    """Factory for creating enum object types
    """
    def __init__(self, enumclass: "typing.Type[Enum]"):
        self.enums = enumclass
        # Validate that all enum keys match the expected format
        for member in enumclass:
            # only upppercase letters, numbers and _ allowed
            for c in member.name:
                if c.isdigit() or c == "_":
                    continue
                if c.isalpha() and c.isupper():
                    continue
                raise RuntimeError("Invalid character '" + c + "' found in enum " + str(enumclass) +
                                   " member " + member.name + ": must all be upper case letters or _ or digits.")
        # self.action = action

    def __call__(self, astring):
        if isinstance(astring, list):
            return [self.__call__(a) for a in astring]
        if isinstance(astring, self.enums):
            return astring  # Allow passing an enum instance
        name = self.enums.__name__
        try:
            # convert the passed value to the enum name
            enum_value_name = astring.upper()  # type: str
            enum_value_name = enum_value_name.replace("-", "_")
            v = self.enums[enum_value_name]
        except KeyError:
            msg = ', '.join([t.name.lower() for t in self.enums])
            msg = '%s: use one of {%s}'%(name, msg)
            raise argparse.ArgumentTypeError(msg)
#       else:
#           self.action.choices = None  # hugly hack to prevent post validation from choices
        return v

    def __repr__(self):
        astr = ', '.join([t.name.lower() for t in self.enums])
        return '%s(%s)' % (self.enums.__name__, astr)


class ConfigLoaderBase(object):
    # will be set later...
    _cheriConfig = None  # type: CheriConfig

    options = dict()  # type: typing.Dict[str, ConfigOptionBase]
    _parsedArgs = None
    _JSON = {}  # type: dict

    showAllHelp = any(s in sys.argv for s in ("--help-all", "--help-hidden")) or "_ARGCOMPLETE" in os.environ

    def __init__(self, option_cls):
        self.__option_cls = option_cls
        self._parser = argparse.ArgumentParser(formatter_class=
                                      lambda prog: argparse.HelpFormatter(prog, width=shutil.get_terminal_size()[0]))
        self.actionGroup = self._parser.add_argument_group("Actions to be performed")
        self.pathGroup = self._parser.add_argument_group("Configuration of default paths")
        self.crossCompileOptionsGroup = self._parser.add_argument_group("Adjust flags used when compiling MIPS/CHERI projects")

        # put this one right at the end since it is not that useful
        self.freebsdGroup = self._parser.add_argument_group("FreeBSD and CheriBSD build configuration")
        self.dockerGroup = self._parser.add_argument_group("Options controlling the use of docker for building")


    def addCommandLineOnlyOption(self, *args, **kwargs):
        """
        :return: A config option that is always loaded from the command line no matter what the default is
        """
        return self.addOption(*args, option_cls=CommandLineConfigOption, **kwargs)

    def addCommandLineOnlyBoolOption(self, *args, default=False, **kwargs) -> bool:
        # noinspection PyTypeChecker
        return self.addOption(*args, option_cls=CommandLineConfigOption, default=default, action="store_true",
                              type=bool, **kwargs)

    @staticmethod
    def __is_enum_type(value_type):
        return isinstance(value_type, type) and issubclass(value_type, Enum)

    def addOption(self, name: str, shortname=None, default=None,
                  type: "typing.Union[typing.Type[str], typing.Callable[[str], Type_T]]"=str,
                  group=None, helpHidden=False, _owningClass: "typing.Type"=None, _fallback_name: str = None,
                  option_cls: "typing.Type[ConfigOptionBase]"=None, **kwargs) -> "Type_T":
        if option_cls is None:
            option_cls = self.__option_cls

        if self.__is_enum_type(type):
            assert "action" not in kwargs or kwargs["action"] == "append", "action should be none or appendfor Enum options"
            assert "choices" not in kwargs, "for enum options choices are the enum names (or set enum_choices)!"
            if "enum_choices" in kwargs:
                kwargs["choices"] = tuple(t.name.lower() for t in kwargs["enum_choices"])
                del kwargs["enum_choices"]
            else:
                kwargs["choices"] = tuple(t.name.lower() for t in type)
            type = _EnumArgparseType(type)

        result = option_cls(name, shortname, default, type, _owningClass, _loader=self, group=group,
                            helpHidden=helpHidden, _fallback_name=_fallback_name, **kwargs)
        assert name not in self.options  # make sure we don't add duplicate options
        self.options[name] = result
        # noinspection PyTypeChecker
        return result

    def addBoolOption(self, name: str, shortname=None, default=False, **kwargs) -> bool:
        # noinspection PyTypeChecker
        return self.addOption(name, shortname, default=default, action="store_true", type=bool, **kwargs)

    def addPathOption(self, name: str, shortname=None, **kwargs) -> Path:
        # we have to make sure we resolve this to an absolute path because otherwise steps where CWD is different fail!
        return self.addOption(name, shortname, type=Path, **kwargs)

    def load(self):
        raise NotImplementedError()

    def finalizeOptions(self, availableTargets, **kwargs):
        raise NotImplementedError()

    def reload(self) -> None:
        """
        Clear all loaded values and force reloading them (useful for tests)
        """
        self.reset()
        self.load()

    def reset(self):
        for option in self.options.values():
            option._cached = None

    @property
    def targets(self) -> "typing.List[str]":
        return self._parsedArgs.targets


class ConfigOptionBase(object):
    def __init__(self, name: str, shortname: str, default, valueType: "typing.Type", _owningClass=None,
                 _loader: ConfigLoaderBase=None, _fallback_name: str=None):
        self.name = name
        self.shortname = shortname
        self.default = default
        self.valueType = valueType
        if isinstance(default, ComputedDefaultValue):
            if callable(default.asString):
                self.default_str = default.asString(_owningClass)
            else:
                self.default_str = str(default.asString)
        elif default is not None:
            if isinstance(default, Enum) or isinstance(valueType, _EnumArgparseType):
                # allow append
                if default == []:
                    self.default_str = "[]"
                else:
                    assert isinstance(valueType, _EnumArgparseType), "default is enum but value type isn't: " + str(valueType)
                    assert isinstance(default, Enum), "Should use enum constant for default and not " + str(default)
                    self.default_str = default.name.lower()
            else:
                self.default_str = str(default)
        self._cached = None
        self._loader = _loader
        self._owningClass = _owningClass  # if none it means the global CheriConfig is the class containing this option
        self._fallback_name = _fallback_name  # for targets such as gdb-mips, etc

    def loadOption(self, config: "CheriConfig", instance: "typing.Optional[SimpleProject]", owner: "typing.Type"):
        result = self._loadOptionImpl(config, self.fullOptionName)
        # fall back from --qtbase-mips/foo to --qtbase/foo
        if result is None and self._fallback_name is not None:
            fallback_option = self._loader.options.get(self._fallback_name)
            assert fallback_option is not None, "Could not find option " + self._fallback_name
            result = fallback_option._loadOptionImpl(config, self.fullOptionName)
            if result is not None and config.verbose:
                print("Using fallback config option value", self._fallback_name, "for", self.name, "->", result)

        if result is None:  # If no option is set fall back to the default
            result = self._getDefaultValue(config, instance)
        # Now convert it to the right type
        try:
            result = self._convertType(result)
        except ValueError as e:
            fatalError("Invalid value for option '", self.fullOptionName,
                       "': could not convert '", result, "': ", str(e), sep="")
            sys.exit()
        return result

    def _loadOptionImpl(self, config: "CheriConfig", target_option_name) -> "typing.Optional[Any]":
        # target_option_name may not be the same as self.fullOptionName if we are loading the fallback value
        raise NotImplementedError()

    @property
    def fullOptionName(self):
        return self.name

    def __get__(self, instance, owner):
        assert instance is not None, "This attribute needs an object instance. Owner = " + str(owner)

        # TODO: would be nice if this was possible (but too much depends on accessing values without instances)
        # if instance is None:
        #     return self
        assert not self._owningClass or issubclass(owner, self._owningClass)
        if self._cached is None:
            # noinspection PyProtectedMember
            # allow getting the value when used on a class as well:
            if instance is None:
                instance = owner
            self._cached = self.loadOption(self._loader._cheriConfig, instance, owner)
        return self._cached

    def _getDefaultValue(self, config: "CheriConfig", instance: "typing.Optional[SimpleProject]"=None):
        if callable(self.default):
            return self.default(config, instance)
        else:
            return self.default

    def _convertType(self, result):
        # check for None to make sure we don't call str(None) which would result in "None"
        if result is None:
            return None
        # print("Converting", result, "to", self.valueType)
        # if the requested type is list, tuple, etc. use shlex.split() to convert strings to lists
        if self.valueType != str and isinstance(result, str):
            if isinstance(self.valueType, type) and issubclass(self.valueType, collections.abc.Sequence):
                stringValue = result
                result = shlex.split(stringValue)
                print(coloured(AnsiColour.magenta, "Config option ", self.fullOptionName, " (", stringValue,
                               ") should be a list, got a string instead -> assuming the correct value is ",
                               result, sep=""))
        if self.valueType == Path:
            expanded = os.path.expanduser(os.path.expandvars(str(result)))
            # print("Expanding env vars in", result, "->", expanded, os.environ)
            result = Path(expanded).absolute()
        else:
            result = self.valueType(result)  # make sure it has the right type (e.g. Path, int, bool, str)
        return result

    def __repr__(self):
        return "<{}({}) type={} cached={}>".format(self.__class__.__name__, self.name, self.valueType, self._cached)


class DefaultValueOnlyConfigOption(ConfigOptionBase):
    def __init__(self, *args, _loader, **kwargs):
        super().__init__(*args, _loader=_loader)

    def _loadOptionImpl(self, config: "CheriConfig", target_option_name):
        return None  # always use the default value


class CommandLineConfigOption(ConfigOptionBase):
    def __init__(self, name: str, shortname: str, default, valueType: "typing.Type", _owningClass,
                 _loader: ConfigLoaderBase, helpHidden: bool, group: argparse._ArgumentGroup,
                 _fallback_name: str=None, **kwargs):
        super().__init__(name, shortname, default, valueType, _owningClass, _loader, _fallback_name)
        # hide obscure options unless --help-hidden/--help/all is passed
        if helpHidden and not self._loader.showAllHelp:
            kwargs["help"] = argparse.SUPPRESS

        # add the default string to help if it is not lambda and help != argparse.SUPPRESS
        hasDefaultHelpText = isinstance(self.default, ComputedDefaultValue) or not callable(self.default)
        assert "default" not in kwargs  # Should be handled manually
        # noinspection PyProtectedMember
        parserObj = group if group else self._loader._parser
        if self.valueType == bool and group is None:
            parserObj = parserObj.add_mutually_exclusive_group()
            kwargs["default"] = None
            assert kwargs["action"] == "store_true"
        if self.shortname:
            action = parserObj.add_argument("--" + self.name, "-" + self.shortname, **kwargs)
        else:
            action = parserObj.add_argument("--" + self.name, **kwargs)
        if self.valueType == bool:
            slashIndex = self.name.rfind("/")
            negatedName = self.name[:slashIndex + 1] + "no-" + self.name[slashIndex + 1:]
            negatedHelp = argparse.SUPPRESS
            # if the default is true we want to show the negated option instead.
            if default is True:
                negatedHelp = kwargs["help"]
                if negatedHelp != argparse.SUPPRESS:
                    if negatedHelp[0].isupper():
                        negatedHelp = negatedHelp[0].lower() + negatedHelp[1:]
                    negatedHelp = "Do not " + negatedHelp
                action.help = argparse.SUPPRESS
            neg = parserObj.add_argument("--" + negatedName, dest=action.dest, default=None, action="store_false",
                                         help=negatedHelp)
            # change the default action value
            neg.default = None
            action.default = None
        if self.default is not None and action.help is not None and hasDefaultHelpText:
            if action.help != argparse.SUPPRESS:
                action.help = action.help + " (default: \'" + self.default_str + "\')"
        assert action.default is None  # we don't want argparse default values!
        assert isinstance(action, argparse.Action)
        assert not action.default  # we handle the default value manually
        assert not action.type  # we handle the type of the value manually
        self.action = action

    def _loadOptionImpl(self, config: "CheriConfig", target_option_name: str):
        from_cmdline = self.loadFromCommandLine()
        return from_cmdline

    # noinspection PyProtectedMember
    def loadFromCommandLine(self):
        assert self._loader._parsedArgs  # load() must have been called before using this object
        # FIXME: check the fallback name here
        assert hasattr(self._loader._parsedArgs, self.action.dest)
        return getattr(self._loader._parsedArgs, self.action.dest)  # from command line


# noinspection PyProtectedMember
class JsonAndCommandLineConfigOption(CommandLineConfigOption):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def _loadOptionImpl(self, config: "CheriConfig", target_option_name: str):
        # First check the value specified on the command line, then load JSON and then fallback to the default
        fromCmdLine = self.loadFromCommandLine()
        # print(fullOptionName, "from cmdline:", fromCmdLine)
        if fromCmdLine is not None:
            if fromCmdLine != self.action.default:
                return fromCmdLine
            # print("From command line == default:", fromCmdLine, self.action.default, "-> trying JSON")
        # try loading it from the JSON file:
        fromJson = self._loadFromJson(self.fullOptionName)
        # print(fullOptionName, "from JSON:", fromJson)
        if fromJson[0] is not None:
            if config.verbose or True:
                print(coloured(AnsiColour.blue, "Overriding default value for", target_option_name,
                               "with value from JSON key", fromJson[1], "->", fromJson[0]))
            return fromJson[0]
        return None  # not found -> fall back to default

    def _lookupKeyInJson(self, fullOptionName: str):
        if fullOptionName in self._loader._JSON:
            return self._loader._JSON[fullOptionName]
        # if there are any / characters treat these as an object reference
        jsonPath = fullOptionName.split(sep="/")
        jsonKey = jsonPath[-1]  # last item is the key (e.g. llvm/build-type -> build-type)
        jsonPath = jsonPath[:-1]  # all but the last item is the path (e.g. llvm/build-type -> llvm)
        jsonObject = self._loader._JSON
        for objRef in jsonPath:
            # Return an empty dict if it is not found
            jsonObject = jsonObject.get(objRef, {})
        return jsonObject.get(jsonKey, None)

    def _loadFromJson(self, fullOptionName: str) -> "typing.Tuple[typing.Optional[typing.Any], typing.Optional[str]]":
        result = self._lookupKeyInJson(fullOptionName)
        used_key = None
        # See if any of the other long option names is a valid key name:
        if result is None:
            for optionName in self.action.option_strings:
                if optionName.startswith("--"):
                    jsonKey = optionName[2:]
                    result = self._lookupKeyInJson(jsonKey)
                    if result is not None:
                        warningMessage("Old JSON key", jsonKey, "used, please use", fullOptionName, "instead")
                        used_key = jsonKey
                        break
        else:
            used_key = fullOptionName
        # FIXME: it's about time I removed this code
        if result is None:
            # also check action.dest (as a fallback so I don't have to update all my config files right now)
            result = self._loader._JSON.get(self.action.dest, None)
            if result is not None:
                print(coloured(AnsiColour.cyan, "Old JSON key", self.action.dest, "used, please use",
                               fullOptionName, "instead"))
        return result, used_key

    # def __get__(self, instance, owner):
    #     ret = super().__get__(instance, owner)
    #     print(self.fullOptionName, "=", ret, "--", type(ret))
    #     return ret


class DefaultValueOnlyConfigLoader(ConfigLoaderBase):
    def __init__(self):
        super().__init__(DefaultValueOnlyConfigOption)
        # Ignore options stored in other classes
        self.options = dict()

    def finalizeOptions(self, availableTargets: list, **kwargs):
        pass

    def load(self):
        pass


# https://stackoverflow.com/a/14902564/894271
def dict_raise_on_duplicates(ordered_pairs):
    """Reject duplicate keys."""
    d = {}
    for k, v in ordered_pairs:
        if k in d:
            raise SyntaxError("duplicate key: %r" % (k,))
        else:
            d[k] = v
    return d

class JsonAndCommandLineConfigLoader(ConfigLoaderBase):
    def __init__(self):
        super().__init__(JsonAndCommandLineConfigOption)
        self._configPath = None  # type: typing.Optional[Path]
        self.configdir = os.getenv("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
        # Choose the default config file based on argv[0]
        # This allows me to have symlinks for e.g. stable-cheribuild.py release-cheribuild.py debug-cheribuild.py
        # that pick up the right config file in ~/.config
        config_prefix = self.get_config_prefix()
        # print("Name is:", program, "prefix:", config_prefix)
        self.defaultConfigPath = Path(self.configdir, config_prefix + "cheribuild.json")
        self.pathGroup.add_argument("--config-file", metavar="FILE", type=str, default=str(self.defaultConfigPath),
                                  help="The config file that is used to load the default settings (default: '" +
                                  str(self.defaultConfigPath) + "')")
        self._parser.add_argument("--help-all", "--help-hidden", action="help", help="Show all help options, including"
                                                                                     " the target-specific ones.")
        # argument groups:
        # self.deprecatedOptionsGroup = _parser.add_argument_group("Old deprecated options", "These should not be used any more")
        self.cheriBitsGroup = self._parser.add_mutually_exclusive_group()
        self.crossCompileGroup = self._parser.add_mutually_exclusive_group()
        self.configureGroup = self._parser.add_mutually_exclusive_group()
        self.completion_excludes = []

    @staticmethod
    def get_config_prefix():
        config_prefix = ""
        program = Path(sys.argv[0]).name
        if program.endswith("cheribuild.py"):
            config_prefix = program[0:-len("cheribuild.py")]
        return config_prefix

    def finalizeOptions(self, availableTargets: list, **kwargs):
        targetOption = self._parser.add_argument("targets", metavar="TARGET", nargs=argparse.ZERO_OR_MORE,
                                                 help="The targets to build", choices=availableTargets + [[]])
        if argcomplete and "_ARGCOMPLETE" in os.environ:
            # if IS_FREEBSD: # FIXME: for some reason this won't work
            self.completion_excludes = ["-t", "--skip-dependencies"]
            if sys.platform.startswith("freebsd"):
                self.completion_excludes += ["--freebsd-builder-copy-only", "--freebsd-builder-hostname",
                                             "--freebsd-builder-output-path"]

            visibleTargets = availableTargets.copy()
            visibleTargets.remove("__run_everything__")
            targetCompleter = argcomplete.completers.ChoicesCompleter(visibleTargets)
            targetOption.completer = targetCompleter
            # make sure we get target completion for the unparsed args too by adding another zero_or more options
            # not sure why this works but it's a nice hack
            unparsed = self._parser.add_argument("targets", metavar="TARGET", type=list, nargs=argparse.ZERO_OR_MORE,
                                                 help=argparse.SUPPRESS, choices=availableTargets)
            unparsed.completer = targetCompleter

    def __load_json_with_comments(self, config_path: Path) -> "typing.Dict[str, typing.Any]":
        """
        Loads a JSON file ignoring any lines that start with '#' or '//'
        :param config_path: path to the json file
        :return: a parsed json dict
        """
        with config_path.open("r", encoding="utf-8") as f:
            json_lines = []
            for line in f.readlines():
                stripped = line.strip()
                if not stripped.startswith("#") and not stripped.startswith("//"):
                    json_lines.append(line)
            # print("".join(jsonLines))
            result = json.loads("".join(json_lines), object_pairs_hook=dict_raise_on_duplicates, encoding="utf-8")
            if self._parsedArgs and self._parsedArgs.verbose is True:
                print("Parsed", config_path, "as", coloured(AnsiColour.cyan, json.dumps(result)))
            return result

    def __load_json_with_includes(self, config_path: Path):
        result = dict()
        try:
            result = self.__load_json_with_comments(config_path)
        except Exception as e:
            print(coloured(AnsiColour.red, "Could not load config file", config_path, "-", e), file=sys.stderr)
            if not sys.__stdin__.isatty() or not input("Invalid config file " + str(config_path) +
                                                       ". Continue? y/[N]").lower().startswith("y"):
                raise
        include_value = result.get("#include")
        if include_value:
            included_path = config_path.parent / include_value
            base_json = self.__load_json_with_includes(included_path)
            base_json.update(result)
            result = base_json
            if self._parsedArgs and self._parsedArgs.verbose is True:
                print(coloured(AnsiColour.cyan, "Included JSON config file", included_path))
                print("New result is", coloured(AnsiColour.cyan, json.dumps(result)))

        return result

    def _load_json_config_file(self) -> None:
        self._JSON = {}
        if not self._configPath:
            self._configPath = Path(os.path.expanduser(self._parsedArgs.config_file)).absolute()
        if self._configPath.exists():
            self._JSON = self.__load_json_with_includes(self._configPath)
        else:
            print(coloured(AnsiColour.green, "Configuration file", self._configPath,
                           "does not exist, using only command line arguments."), file=sys.stderr)

    def load(self):
        if argcomplete and "_ARGCOMPLETE" in os.environ:
            argcomplete.autocomplete(
                self._parser,
                always_complete_options=None,  # don't print -/-- by default
                exclude=self.completion_excludes,  # hide these options from the output
                print_suppressed=True,  # also include target-specific options
            )
        self._parsedArgs, trailingTargets = self._parser.parse_known_args()
        # print(self._parsedArgs, trailingTargets)
        self._parsedArgs.targets += trailingTargets
        self._load_json_config_file()
        # Now validate the config file
        self._validateConfigFile()

    def __validate(self, prefix: str, key: str, value) -> bool:
        fullname = prefix + key
        if isinstance(value, dict):
            for k, v in value.items():
                self.__validate(fullname + "/", k, v)
            return True

        if fullname == "#include":
            return True

        if fullname in self.options:
            return True
        # see if it is one of the alternate names is valid
        for option in self.options.values():
            # only handle alternate names that aren't one character long
            if option.shortname and len(option.shortname) > 1:
                alternateName = option.shortname.lstrip("-")
                if fullname == alternateName:
                    return True  # fine

        print(coloured(AnsiColour.red, "Unknown config option '", fullname, "' in ", self._configPath, sep=""))
        return False

    def _validateConfigFile(self):
        for k, v in self._JSON.items():
            self.__validate("", k, v)

    def reset(self) -> None:
        super().reset()
        self._load_json_config_file()
