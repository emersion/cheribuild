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
import os
import shutil
from pathlib import Path

from ..config.loader import ComputedDefaultValue
from .project import *
from ..utils import *


class BuildGnuBinutils(AutotoolsProject):
    target = "gnu-binutils"
    projectName = "gnu-binutils"
    repository = "https://github.com/CTSRD-CHERI/binutils.git"
    gitBranch = "cheribsd"  # the default branch "cheri" won't work for cross-compiling
    defaultInstallDir = AutotoolsProject._installToSDK

    @classmethod
    def setupConfigOptions(cls, **kwargs):
        super().setupConfigOptions()
        cls.fullInstall = cls.addBoolOption("install-all-tools", help="Whether to install all binutils tools instead"
                                                                      "of only as, ld and objdump")

    def __init__(self, config: CheriConfig):
        super().__init__(config)
        # http://marcelog.github.io/articles/cross_freebsd_compiler_in_linux.html

        # If we don't use a patched binutils version on linux we get an ld binary that is
        # only able to handle 32 bit mips:
        # GNU ld (GNU Binutils) 2.18
        # Supported emulations:
        #     elf32ebmip

        # The version from the FreeBSD source tree supports the right targets:
        # GNU ld 2.17.50 [FreeBSD] 2007-07-03
        # Supported emulations:
        #    elf64btsmip_fbsd
        #    elf32btsmip_fbsd
        #    elf32ltsmip_fbsd
        #    elf64btsmip_fbsd
        #    elf64ltsmip_fbsd
        #    elf32btsmipn32_fbsd
        #    elf32ltsmipn32_fbsd
        self.configureArgs.extend([
            # on cheri gcc -dumpmachine returns mips64-undermydesk-freebsd, however this is not accepted by BFD
            # if we just pass --target=mips64 this apparently defaults to mips64-unknown-elf on freebsd
            # and also on Linux, but let's be explicit in case it assumes ELF binaries to target linux
            # "--target=mips64-undermydesk-freebsd",  # binutils for MIPS64/CHERI
            "--target=mips64-unknown-freebsd",  # binutils for MIPS64/FreeBSD
            "--disable-werror",  # -Werror won't work with recent compilers
            "--enable-ld",  # enable linker (is default, but just be safe)
            "--enable-libssp",  # not sure if this is needed
            "--enable-64-bit-bfd",  # Make sure we always have 64 bit support
            "--enable-targets=all",
            "--disable-gprof",
            "--disable-gold",
            "--disable-nls",
            # TODO: --with-sysroot doesn't work properly so we need to tell clang not to pass the --sysroot option
            "--with-sysroot=" + str(self.config.sdkSysrootDir),  # as we pass --sysroot to clang we need this option
            "--disable-info",
            #  "--program-prefix=cheri-unknown-freebsd-",
            "MAKEINFO=missing",  # don't build docs, this will fail on recent Linux systems
        ])
        self.configureArgs.append("--disable-shared")
        # newer compilers will default to -std=c99 which will break binutils:
        cflags = "-std=gnu89 -O2"
        info = getCompilerInfo(Path(os.getenv("CC", shutil.which("cc"))))
        if info.compiler == "clang" or (info.compiler == "gcc" and info.version >= (4, 6, 0)):
            cflags += " -Wno-unused"
        self.configureEnvironment["CFLAGS"] = cflags

    def update(self):
        self._ensureGitRepoIsCloned(srcDir=self.sourceDir, remoteUrl=self.repository, initialBranch=self.gitBranch)
        # Make sure we have the version that can compile FreeBSD binaries
        status = runCmd("git", "status", "-b", "-s", "--porcelain", "-u", "no",
                        captureOutput=True, printVerboseOnly=True, cwd=self.sourceDir)
        if not status.stdout.startswith(b"## cheribsd"):
            branches = runCmd("git", "branch", "--list", captureOutput=True, printVerboseOnly=True).stdout
            if b" cheribsd" not in branches:
                runCmd("git", "checkout", "-b", "cheribsd", "--track", "origin/cheribsd")
        runCmd("git", "checkout", "cheribsd", cwd=self.sourceDir)
        super().update()

    def compile(self, **kwargs):
        self.runMake("all-ld", logfileName="build")
        self.runMake("all-gas", logfileName="build")
        self.runMake("all-binutils", logfileName="build")

    def install(self, **kwargs):
        bindir = self.installDir / "bin"
        if not self.fullInstall:
            # we don't want to install all programs, as the rest comes from elftoolchain
            self.runMake("install-gas", logfileName="install", appendToLogfile=True, parallel=False)
            self.deleteFile(bindir / "mips64-unknown-freebsd-ld")
            self.runMake("install-ld", logfileName="install", appendToLogfile=True, parallel=False)
            # we also need the linker scripts so this is not enough:
            # self.installFile(self.buildDir / "ld/ld-new", bindir / "ld.bfd", force=True)
            self.moveFile(bindir / "mips64-unknown-freebsd-ld", bindir / "mips64-unknown-freebsd-ld.bfd")
            installedTools = ["as", "ld.bfd"]
            # copy objdump from the build dir
            self.installFile(self.buildDir / "binutils/objdump", bindir / "mips64-unknown-freebsd-objdump")
            installedTools.append("objdump")
        else:
            super().install()
            installedTools = "addr2line ranlib strip ar nm readelf as objcopy size c++filt objdump strings".split()
            # create links for ld:
            self.createBuildtoolTargetSymlinks(bindir / "ld.bfd")
        for tool in installedTools:
            prefixedName = "mips64-unknown-freebsd-" + tool
            if not (bindir / prefixedName).is_file():
                fatalError("Binutils binary", prefixedName, "is missing!")
            # create the right symlinks to the tool (ld -> mips64-unknown-elf-ld, etc)
            # Also symlink cheri-unknown-freebsd-ld -> ld (and the other targets)
            self.createBuildtoolTargetSymlinks(bindir / prefixedName, toolName=tool, createUnprefixedLink=True)

    def process(self):
        self.warning("GNU binutils should only be built if you know what you are doing since the linker "
                     "is incredibly buggy and the assembler doesn't support all features that clang does.")
        if not self.queryYesNo("Are you sure you want to build this code?", defaultResult=False, forceResult=True):
            return
        super().process()

class BuildGPLv3Binutils(BuildGnuBinutils):
    target = "gplv3-binutils"
    projectName = "GPLv3-BinUtils"
    # This is much faster to clone than the official repo
    repository = "https://github.com/arichardson/binutils-gdb.git"
    gitBranch = "cheribsd"

    def __init__(self, config: CheriConfig):
        super().__init__(config)
        self.projectName = ""
        # self.configureArgs.append("--enable-gold")
        del self.configureEnvironment["CFLAGS"]

    def update(self):
        AutotoolsProject.update(self)
