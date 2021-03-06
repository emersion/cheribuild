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

from .crosscompileproject import *
from .cheribsd import BuildCHERIBSD
from ..llvm import BuildLLVM
from ...config.loader import ComputedDefaultValue
from ...utils import statusUpdate
from pathlib import Path


class BuildLLVMTestSuite(CrossCompileCMakeProject):
    repository = "https://github.com/CTSRD-CHERI/llvm-test-suite.git"
    dependencies = ["llvm"]
    defaultCMakeBuildType = "Debug"
    projectName = "llvm-test-suite"
    defaultSourceDir = ComputedDefaultValue(
        function=lambda config, project: Path(config.sourceRoot / "llvm-test-suite"),
        asString="$SOURCE_ROOT/llvm-test-suite")

    def _find_in_sdk_or_llvm_build_dir(self, name) -> Path:
        if (BuildLLVM.getBuildDir(self, self.config) / "bin" / name).exists():
            return BuildLLVM.getBuildDir(self, self.config) / "bin" / name
        return self.config.sdkBinDir / name

    def __init__(self, config):
        super().__init__(config)
        self.add_cmake_options(
            TEST_SUITE_LLVM_SIZE=self._find_in_sdk_or_llvm_build_dir("llvm-size"),
            TEST_SUITE_LLVM_PROFDATA=self._find_in_sdk_or_llvm_build_dir("llvm-profdata"),
            TEST_SUITE_LIT=self._find_in_sdk_or_llvm_build_dir("llvm-lit")
        )
        # TODO: fix these issues
        self.cross_warning_flags += ["-Wno-error=format", "-Werror=mips-cheri-prototypes"]
        if not self.compiling_for_host():
            self.add_cmake_options(TEST_SUITE_HOST_CC="/usr/bin/cc")
            # we want to link against libc++ not libstdc++ (and for some reason we need to specify libgcc_eh too
            self.add_cmake_options(TEST_SUITE_CXX_LIBRARY="-lc++;-lgcc_eh")

    def install(self, **kwargs):
        statusUpdate("No install step for llvm-test-suite")
