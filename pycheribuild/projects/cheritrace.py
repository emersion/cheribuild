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
from .project import *
from ..utils import *


class BuildCheriTrace(CMakeProject):
    dependencies = ["llvm"]
    repository = "https://github.com/CTSRD-CHERI/cheritrace.git"
    defaultInstallDir = CMakeProject._installToSDK
    appendCheriBitsToBuildDir = True

    @classmethod
    def setupConfigOptions(cls):
        super().setupConfigOptions()
        cls.include_python_bindings = cls.addBoolOption("python-bindings")

    def __init__(self, config: CheriConfig):
        super().__init__(config)
        self._addRequiredSystemTool("clang")
        self._addRequiredSystemTool("clang++")
        self.llvmConfigPath = self.config.sdkDir / "bin/llvm-config"
        self.add_cmake_options(
            LLVM_CONFIG=self.llvmConfigPath,
            CMAKE_C_COMPILER=self.config.clangPath,
            CMAKE_CXX_COMPILER=self.config.clangPlusPlusPath,
            PYTHON_BINDINGS=self.include_python_bindings
        )

    def configure(self):
        if not self.llvmConfigPath.is_file():
            self.dependencyError("Could not find llvm-config from CHERI LLVM.",
                                 installInstructions="Build target 'llvm' first.")
        super().configure()
