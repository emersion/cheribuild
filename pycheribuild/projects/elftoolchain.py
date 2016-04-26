import shutil
from ..project import Project
from ..utils import *


class BuildElfToolchain(Project):
    def __init__(self, config: CheriConfig):
        super().__init__(config, installDir=config.sdkDir,
                         gitUrl="https://github.com/emaste/elftoolchain.git")
        self.buildDir = self.sourceDir
        if IS_LINUX:
            self.requiredSystemTools = ["bmake"]
            self.makeCommand = "bmake"
        else:
            self.makeCommand = "make"

        self.gitBranch = "master"
        # self.makeArgs = ["WITH_TESTS=no", "-DNO_ROOT"]
        # TODO: build static?
        self.makeArgs = ["WITH_TESTS=no", "LDSTATIC=-static"]

    def compile(self):
        targets = ["common", "libelf", "libelftc"]
        # tools that we want to build:
        targets += ["brandelf"]
        for tgt in targets:
            self.runMake([self.makeCommand, self.config.makeJFlag] + self.makeArgs,
                         "all", cwd=self.sourceDir / tgt)

    def install(self):
        # self.runMake([self.makeCommand, self.config.makeJFlag, "DESTDIR=" + str(self.installDir)] + self.makeArgs,
        #              "install", cwd=self.sourceDir)
        # make install requires root, just build binaries statically and copy them
        self.copyFile(self.sourceDir / "brandelf/brandelf", self.installDir / "bin/brandelf", force=True)