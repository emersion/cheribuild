#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK
# -
# Copyright (c) 2016-2017 SRI International
# Copyright (c) 2017 Alex Richardson
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
# runtests.py - run FreeBSD tests and export them to a tarfile via a disk
# device.
#
import argparse
import datetime
import os
import pexpect
import shlex
import shutil
import subprocess
import sys
import time
import tempfile
import typing
from pathlib import Path

STARTING_INIT = "start_init: trying /sbin/init"
BOOT_FAILURE = "Enter full pathname of shell or RETURN for /bin/sh"
SHELL_OPEN = "exec /bin/sh"
LOGIN = "login:"
PROMPT = "root@.+:.+# "  # /bin/csh
PROMPT_SH = "# "  # /bin/sh
STOPPED = "Stopped at"
PANIC = "panic: trap"
PANIC_KDB = "KDB: enter: panic"
CHERI_TRAP = "USER_CHERI_EXCEPTION: pid \\d+ tid \\d+ \(.+\)"


def info(*args, **kwargs):
    print(*args, file=sys.stderr, flush=True, **kwargs)


def success(*args, **kwargs):
    print("\n\033[0;32m", *args, "\033[0m", sep="", file=sys.stderr, flush=True, **kwargs)


# noinspection PyShadowingBuiltins
def failure(*args, exit=True, **kwargs):
    print("\n\033[0;31m", *args, "\033[0m", sep="", file=sys.stderr, flush=True, **kwargs)
    if exit:
        time.sleep(1)  # to get the remaining output
        sys.exit(1)
    return False


def run_host_command(*args, **kwargs):
    if kwargs:
        info("\033[0;33mRunning", *args, "with", kwargs.copy(), "\033[0m")
    else:
        info("\033[0;33mRunning", *args, "\033[0m")
    subprocess.check_call(*args, **kwargs)


def decompress(archive: Path, force_decompression: bool, *, keep_archive=True, cmd=None) -> Path:
    result = archive.with_suffix("")
    if result.exists():
        if not force_decompression:
            return result
        result.unlink()
    info("Extracting", archive)
    if keep_archive:
        cmd = cmd + ["-k"]
    run_host_command(cmd + [str(archive)])
    return result


def maybe_decompress(path: Path, force_decompression: bool, keep_archive=True) -> Path:
    # drop the suffix and then try decompressing
    def bunzip(archive):
        return decompress(archive, force_decompression, cmd=["bunzip2", "-v"], keep_archive=keep_archive)

    def unxz(archive):
        return decompress(archive, force_decompression, cmd=["xz", "-d", "-v"], keep_archive=keep_archive)

    if path.suffix == ".bz2":
        return bunzip(path)
    elif path.suffix == ".xz":
        return unxz(path)
    # try adding the arhive suffix suffix
    elif path.with_suffix(path.suffix + ".bz2").exists():
        return bunzip(path.with_suffix(path.suffix + ".bz2"))
    elif path.with_suffix(path.suffix + ".xz").exists():
        return unxz(path.with_suffix(path.suffix + ".xz"))
    elif not path.exists():
        sys.exit("Could not find " + str(path))
    assert path.exists(), path
    return path


def run_cheribsd_command(qemu: pexpect.spawn, cmd: str, expected_output=None, error_output=None, timeout=60):
    qemu.sendline(cmd)
    if expected_output:
        qemu.expect(expected_output)
    results = [pexpect.TIMEOUT, PROMPT, "/bin/sh: [\\w\\d_-]+: not found", CHERI_TRAP]
    if error_output:
        results.append(error_output)
    i = qemu.expect(results, timeout=timeout)
    if i == 0:
        failure("timeout running ", cmd)
    elif i == 2:
        failure("Command not found!")
    elif i == 3:
        # wait up to 20 seconds for a prompt to ensure the dump output has been printed
        qemu.expect([pexpect.TIMEOUT, PROMPT], timeout=20)
        qemu.flush()
        failure("Got CHERI TRAP!")
    elif i == 4:
        # wait up to 5 seconds for a prompt to ensure the full output has been printed
        qemu.expect([pexpect.TIMEOUT, PROMPT], timeout=5)
        qemu.flush()
        failure("Matched error output ", error_output)

def run_cheribsd_command_or_die(qemu: pexpect.spawn, cmd: str, timeout=600):
    qemu.sendline(test_command +
                  " ;if test $? -eq 0; then echo 'COMMAND' 'SUCCESSFUL'; else echo 'COMMAND' 'FAILED'; fi")
    i = qemu.expect([pexpect.TIMEOUT, "COMMAND SUCCESSFUL", "COMMAND FAILED", PANIC, CHERI_TRAP, STOPPED], timeout=timeout)
    testtime = datetime.datetime.now() - run_tests_starttime
    if i == 0:  # Timeout
        return failure("timeout after", testtime, "waiting for tests: ", str(qemu), exit=False)
    elif i == 1:
        success("===> Tests completed!")
        success("Running tests took ", testtime)
        return True
    else:
        return failure("error after ", testtime, "while running tests : ", str(qemu), exit=False)


def setup_ssh(qemu: pexpect.spawn, pubkey: Path):
    run_cheribsd_command(qemu, "mkdir -p /root/.ssh")
    contents = pubkey.read_text(encoding="utf-8").strip()
    run_cheribsd_command(qemu, "echo " + shlex.quote(contents) + " >> /root/.ssh/authorized_keys")
    run_cheribsd_command(qemu, "chmod 600 /root/.ssh/authorized_keys")
    run_cheribsd_command(qemu, "echo 'PermitRootLogin without-password' >> /etc/ssh/sshd_config")
    # TODO: check for bluehive images without /sbin/service
    run_cheribsd_command(qemu, "cat /root/.ssh/authorized_keys", expected_output="ssh-")
    run_cheribsd_command(qemu, "grep -n PermitRootLogin /etc/ssh/sshd_config")
    qemu.sendline("service sshd restart")
    i = qemu.expect([pexpect.TIMEOUT, "service: not found", "Starting sshd."], timeout=120)
    if i == 0:
        failure("Timed out setting up SSH keys")
    qemu.expect(PROMPT)
    time.sleep(2)  # sleep for two seconds to avoid a rejection
    success("===> SSH authorized_keys set up")


def set_posix_sh_prompt(child):
    success("===> setting PS1")
    # Make the prompt match PROMPT
    child.sendline("export PS1=\"{}\"".format("root@qemu-test:~ \\\\$ "))
    # No need to eat the echoed command since we end the prompt with \$ (expands to # or $) instead of #
    # Find the prompt
    j = child.expect([pexpect.TIMEOUT, PROMPT], timeout=60)
    if j == 0:  # timeout
        failure("timeout after setting command prompt ", str(child))
    success("===> successfully set PS1")


def boot_cheribsd(qemu_cmd: str, kernel_image: str, disk_image: str, ssh_port: typing.Optional[int], *, smb_dir: str=None) -> pexpect.spawn:
    user_network_args = "user,id=net0,ipv6=off"
    if smb_dir:
        user_network_args += ",smb=" + smb_dir
    if ssh_port is not None:
        user_network_args += ",hostfwd=tcp::" + str(ssh_port) + "-:22"
    qemu_args = ["-M", "malta", "-kernel", kernel_image, "-m", "2048", "-nographic",
                 #  ssh forwarding:
                 "-net", "nic", "-net", user_network_args]
    if disk_image:
        qemu_args += ["-hda", disk_image]
    success("Starting QEMU: ", qemu_cmd, " ", " ".join(qemu_args))
    qemu_starttime = datetime.datetime.now()
    child = pexpect.spawnu(qemu_cmd, qemu_args, echo=False, timeout=60)
    # child.logfile=sys.stdout.buffer
    child.logfile_read = sys.stdout
    # ignore SIGINT for the python code, the child should still receive it
    # signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        i = child.expect([pexpect.TIMEOUT, STARTING_INIT, BOOT_FAILURE, PANIC_KDB, PANIC, CHERI_TRAP, STOPPED], timeout=5 * 60)
        if i == 0:  # Timeout
            failure("timeout before booted: ", str(child))
        elif i != 1:  # start up scripts failed
            failure("start up scripts failed to run")
        userspace_starttime = datetime.datetime.now()
        success("===> init running (kernel startup time: ", userspace_starttime - qemu_starttime, ")")

        i = child.expect([pexpect.TIMEOUT, LOGIN, SHELL_OPEN, BOOT_FAILURE, PANIC, CHERI_TRAP, STOPPED], timeout=15 * 60)
        if i == 0:  # Timeout
            failure("timeout awaiting login prompt: ", str(child))
        elif i == 1:
            success("===> got login prompt")
            child.sendline("root")

            i = child.expect([pexpect.TIMEOUT, PROMPT, PROMPT_SH],
                             timeout=3 * 60)  # give CheriABI csh 3 minutes to start
            if i == 0:  # Timeout
                failure("timeout awaiting command prompt ")
            if i == 1:  # /bin/csh prompt
                success("===> got csh command prompt, starting POSIX sh")
                # csh is weird, use the normal POSIX sh instead
                child.sendline("sh")
                i = child.expect([pexpect.TIMEOUT, PROMPT, PROMPT_SH], timeout=3 * 60) # give CheriABI sh 3 minutes to start
                if i == 0:  # Timeout
                    failure("timeout starting /bin/sh")
                elif i == 1:  # POSIX sh with PS1 set
                    success("===> started POSIX sh (PS1 already set)")
                elif i == 2:  # POSIX sh without PS1
                    success("===> started POSIX sh (PS1 not set)")
                    set_posix_sh_prompt(child)
            if i == 2:  # /bin/sh prompt
                success("===> got /sbin/sh prompt")
                set_posix_sh_prompt(child)
        elif i == 2:  # shell started from /etc/rc:
            child.expect_exact(PROMPT_SH, timeout=30)
            success("===> /etc/rc completed, got command prompt")
            # set up network (bluehive image tries to use atse0)
            success("===> Setting up QEMU networking")
            child.sendline("ifconfig le0 up && dhclient le0")
            i = child.expect([pexpect.TIMEOUT, "DHCPACK from 10.0.2.2", "dhclient already running"], timeout=120)
            if i == 0:  # Timeout
                failure("timeout awaiting dhclient ", str(child))
            if i == 1:
                i = child.expect([pexpect.TIMEOUT, "bound to"], timeout=120)
                if i == 0:  # Timeout
                   failure("timeout awaiting dhclient ", str(child))
            success("===> le0 bound to QEMU networking")
            child.expect_exact(PROMPT_SH, timeout=30)
            set_posix_sh_prompt(child)
        else:
            failure("error during boot login prompt: ", str(child))
        success("===> booted CheriBSD (userspace startup time: ", datetime.datetime.now() - userspace_starttime, ")")
    except KeyboardInterrupt:
        failure("Keyboard interrupt during boot", exit=False)
    return child


def runtests(qemu: pexpect.spawn, test_archives: list, test_command: str, smb_dir: typing.Optional[Path],
             ssh_keyfile: typing.Optional[str], ssh_port: typing.Optional[int], timeout: int,
             test_function: "typing.Callable[[pexpect.spawn, ...], bool]"=None) -> bool:
    setup_tests_starttime = datetime.datetime.now()
    # disable coredumps, otherwise we get no space left on device errors
    run_cheribsd_command(qemu, "sysctl kern.coredump=0")
    # create tmpfs on opt
    run_cheribsd_command(qemu, "mkdir -p /opt && mount -t tmpfs -o size=500m tmpfs /opt")
    # ensure that /usr/local exists and if not create it as a tmpfs (happens in the minimal image)
    run_cheribsd_command(qemu, "mkdir -p /usr/local && mount -t tmpfs -o size=300m tmpfs /usr/local")
    run_cheribsd_command(qemu, "df -h", expected_output="/opt")
    info("\nWill transfer the following archives: ", test_archives)
    # strip the .pub from the key file
    for archive in test_archives:
        if smb_dir:
            run_host_command(["tar", "xJf", str(archive), "-C", str(smb_dir)])
        else:
            # Extract to temporary directory and scp over
            with tempfile.TemporaryDirectory(dir=os.getcwd(), prefix="test_files_") as tmp:
                run_host_command(["tar", "xJf", str(archive), "-C", tmp])
                private_key = str(Path(ssh_keyfile).with_suffix(""))
                scp_cmd = ["scp", "-B", "-r", "-P", str(ssh_port), "-o", "StrictHostKeyChecking=no",
                           "-o", "UserKnownHostsFile=/dev/null",
                           "-i", shlex.quote(private_key), ".", "root@localhost:/"]
                # use script for a fake tty to get progress output from scp
                if sys.platform.startswith("linux"):
                    scp_cmd = ["script", "--quiet", "--return", "--command", " ".join(scp_cmd), "/dev/null"]
                run_host_command(["ls", "-la"], cwd=tmp)
                run_host_command(scp_cmd, cwd=tmp)
    if test_archives:
        time.sleep(5)  # wait 5 seconds to make sure the disks have synced
    # See how much space we have after running scp
    run_cheribsd_command(qemu, "df -h", expected_output="/opt")
    success("Preparing test enviroment took ", datetime.datetime.now() - setup_tests_starttime)

    run_tests_starttime = datetime.datetime.now()
    # Run the tests (allowing custom test functions)
    if test_function:
        return test_function(qemu, ssh_keyfile=ssh_keyfile, ssh_port=ssh_port)

    qemu.sendline(test_command +
                  " ;if test $? -eq 0; then echo 'TESTS' 'COMPLETED'; else echo 'TESTS' 'FAILED'; fi")
    i = qemu.expect([pexpect.TIMEOUT, "TESTS COMPLETED", "TESTS FAILED", PANIC, STOPPED], timeout=timeout)
    testtime = datetime.datetime.now() - run_tests_starttime
    if i == 0:  # Timeout
        return failure("timeout after", testtime, "waiting for tests: ", str(qemu), exit=False)
    elif i == 1:
        success("===> Tests completed!")
        success("Running tests took ", testtime)
        run_cheribsd_command(qemu, "df -h", expected_output="/opt")  # see how much space we have now
        return True
    else:
        return failure("error after ", testtime, "while running tests : ", str(qemu), exit=False)


def main(test_function=None, argparse_setup_callback: "typing.Callable[[argparse.ArgumentParser], None]"=None,
         argparse_adjust_args_callback: "typing.Callable[[argparse.Namespace], None]"=None):
    # TODO: look at click package?
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--qemu-cmd", default="qemu-system-cheri")
    parser.add_argument("--kernel", default="/usr/local/share/cheribsd/cheribsd-malta64-kernel")
    parser.add_argument("--disk-image", default=None, # default="/usr/local/share/cheribsd/cheribsd-full.img"
                        )
    parser.add_argument("--extract-images-to", help="Path where the compressed images should be extracted to")
    parser.add_argument("--reuse-image", action="store_true")
    parser.add_argument("--keep-compressed-images", action="store_true", default=True, dest="keep_compressed_images")
    parser.add_argument("--no-keep-compressed-images", action="store_false", dest="keep_compressed_images")
    parser.add_argument("--ssh-key", default=os.path.expanduser("~/.ssh/id_ed25519.pub"))
    parser.add_argument("--ssh-port", type=int, default=12345)
    parser.add_argument("--use-smb-instead-of-ssh", action="store_true")
    parser.add_argument("--smb-mount-directory", help="directory used for sharing data with the QEMU guest via smb")
    parser.add_argument("--test-archive", "-t", action="append", nargs=1)
    parser.add_argument("--test-command", "-c")
    parser.add_argument("--test-timeout", "-tt", type=int, default=60 * 60)
    parser.add_argument("--interact", "-i", action="store_true")
    if argparse_setup_callback:
        argparse_setup_callback(parser)
    try:
        # noinspection PyUnresolvedReferences
        import argcomplete
        argcomplete.autocomplete(parser)
    except ImportError:
        pass

    args = parser.parse_args()
    if argparse_adjust_args_callback:
        argparse_adjust_args_callback(args)
    if shutil.which(args.qemu_cmd) is None:
        sys.exit("ERROR: QEMU binary " + args.qemu_cmd + " doesn't exist")

    starttime = datetime.datetime.now()

    # Skip all ssh setup if we are using smb instead:
    if args.use_smb_instead_of_ssh:
        args.ssh_key = None
        args.ssh_port = None

    # validate args:
    test_archives = []  # type: list
    if args.test_archive:
        if args.use_smb_instead_of_ssh and not args.smb_mount_directory:
            failure("--smb-mount-directory is required if ssh is disabled")
        info("Using the following test archives:", args.test_archive)
        if not args.use_smb_instead_of_ssh and not Path(args.ssh_key).exists():
            failure("SSH key missing: ", args.ssh_key)
        for test_archive in args.test_archive:
            if isinstance(test_archive, list):
                test_archive = test_archive[0]
            if not Path(test_archive).exists():
                failure("Test archive is missing: ", test_archive)
            if not test_archive.endswith(".tar.xz"):
                failure("Currently only .tar.xz archives are supported")
            test_archives.append(test_archive)
        if not args.test_command:
            failure("WARNING: No test command specified, tests will fail", exit=False)
            args.test_command = "false"

    force_decompression = not args.reuse_image  # type: bool
    keep_compressed_images = args.keep_compressed_images
    if args.extract_images_to:
        os.makedirs(args.extract_images_to, exist_ok=True)
        new_kernel_path = os.path.join(args.extract_images_to, Path(args.kernel).name)
        shutil.copy(args.kernel, new_kernel_path)
        args.kernel = new_kernel_path
        if args.disk_image:
            new_image_path = os.path.join(args.extract_images_to, Path(args.disk_image).name)
            shutil.copy(args.disk_image, new_image_path)
            args.disk_image = new_image_path

        force_decompression = True
        keep_compressed_images = False
    kernel = str(maybe_decompress(Path(args.kernel), force_decompression, keep_archive=keep_compressed_images))
    diskimg = None
    if args.disk_image:
        diskimg = str(maybe_decompress(Path(args.disk_image), force_decompression, keep_archive=keep_compressed_images))

    boot_starttime = datetime.datetime.now()
    qemu = boot_cheribsd(args.qemu_cmd, kernel, diskimg, args.ssh_port, smb_dir=args.smb_mount_directory)
    success("Booting CheriBSD took: ", datetime.datetime.now() - boot_starttime)

    tests_okay = True
    if test_archives or args.test_command or test_function:
        # noinspection PyBroadException
        try:
            if not args.use_smb_instead_of_ssh:
                setup_ssh_starttime = datetime.datetime.now()
                setup_ssh(qemu, Path(args.ssh_key))
                info("Setting up SSH took: ", datetime.datetime.now() - setup_ssh_starttime)
            tests_okay = runtests(qemu, test_archives=test_archives, test_command=args.test_command,
                                  ssh_keyfile=args.ssh_key, ssh_port=args.ssh_port, timeout=args.test_timeout,
                                  smb_dir=args.smb_mount_directory, test_function=test_function)
        except Exception:
            import traceback
            traceback.print_exc(file=sys.stderr)
            failure("FAILED to run tests!! ", exit=False)
            tests_okay = False
        except KeyboardInterrupt:
            failure("Tests interrupted!!! ", exit=False)
            tests_okay = False

    if args.interact:
        success("===> Interacting with CheriBSD, use CTRL+A,x to exit")
        # interac() prints all input+output -> disable logfile
        qemu.logfile = None
        qemu.logfile_read = None
        qemu.logfile_send = None
        while True:
            try:
                if not qemu.isalive():
                    break
                qemu.interact()
            except KeyboardInterrupt:
                continue

    success("===> DONE")
    info("Total execution time:", datetime.datetime.now() - starttime)
    if not tests_okay:
        exit(1)


if __name__ == "__main__":
    main()
