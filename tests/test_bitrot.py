"""
NOTE: those tests are ordered and require pytest-order to run correctly.
"""

from __future__ import annotations

import getpass
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
from textwrap import dedent

import pytest


TMP = Path("/tmp/")


ReturnCode = int
StdOut = list[str]
StdErr = list[str]


def bitrot(*args: str) -> tuple[ReturnCode, StdOut, StdErr]:
    cmd = [sys.executable, "-m", "bitrot"]
    cmd.extend(args)
    res = subprocess.run(cmd, capture_output=True)
    stdout = (res.stdout or b"").decode("utf8")
    stderr = (res.stderr or b"").decode("utf8")
    return res.returncode, lines(stdout), lines(stderr)


def bash(script, empty_dir: bool = False) -> bool:
    username = getpass.getuser()
    test_dir = TMP / f"bitrot-dir-{username}"
    if empty_dir and test_dir.is_dir():
        os.chdir(TMP)
        shutil.rmtree(test_dir)
    test_dir.mkdir(exist_ok=True)
    os.chdir(test_dir)

    preamble = """
        set -euxo pipefail
        LC_ALL=en_US.UTF-8
        LANG=en_US.UTF-8
        """

    if script:
        # We need to wait a second for modification timestamps to differ so that
        # the ordering of the output stays the same every run of the tests.
        preamble += """
        sleep 1
        """

    script_path = TMP / "bitrot-test.bash"
    script_path.write_text(dedent(preamble + script))
    script_path.chmod(0o755)

    out = subprocess.run(["bash", str(script_path)], capture_output=True)
    if out.returncode:
        print(f"Non-zero return code {out.returncode} when running {script_path}")
        if out.stdout:
            print(out.stdout)
        if out.stderr:
            print(out.stderr)
        return False
    return True


def lines(s: str) -> list[str]:
    r"""Only return non-empty lines that weren't killed by \r."""
    return [
        line.rstrip()
        for line in s.splitlines(keepends=True)
        if line and line.rstrip() and line[-1] != "\r"
    ]


@pytest.mark.order(1)
def test_command_exists() -> None:
    rc, out, err = bitrot("--help")
    assert rc == 0
    assert not err
    assert out[0].startswith("usage:")

    assert bash("", empty_dir=True)


@pytest.mark.order(2)
def test_new_files_in_a_tree_dir() -> None:
    assert bash(
        """
        mkdir -p nonemptydirs/dir2/
        touch nonemptydirs/dir2/new-file-{a,b}.txt
        echo $RANDOM >> nonemptydirs/dir2/new-file-b.txt
        """
    )
    rc, out, err = bitrot("-v")
    assert rc == 0
    # allow non-error stderr (human messages) but no error lines
    assert not any(line.lower().startswith("error:") for line in err)
    # human-oriented messages are on stderr
    assert err[0] == "Finished. 0.00 MiB of data read. 0 errors found."
    assert err[1] == "2 entries in the database. 2 entries new:"
    assert err[2] == "  ./nonemptydirs/dir2/new-file-a.txt"
    assert err[3] == "  ./nonemptydirs/dir2/new-file-b.txt"
    assert err[4] == "Updating bitrot.sha512... done."


@pytest.mark.order(3)
def test_modified_files_in_a_tree_dir() -> None:
    assert bash(
        """
        echo $RANDOM >> nonemptydirs/dir2/new-file-a.txt
        """
    )
    rc, out, err = bitrot("-v")
    assert rc == 0
    assert not any(line.lower().startswith("error:") for line in err)
    assert err[0] == "Checking bitrot.db integrity... ok."
    assert err[2] == "2 entries in the database. 1 entries updated:"
    assert err[3] == "  ./nonemptydirs/dir2/new-file-a.txt"
    assert err[4] == "Updating bitrot.sha512... done."


@pytest.mark.order(4)
def test_renamed_files_in_a_tree_dir() -> None:
    assert bash(
        """
        mv nonemptydirs/dir2/new-file-a.txt nonemptydirs/dir2/new-file-a.txt2
        """
    )
    rc, out, err = bitrot("-v")
    assert rc == 0
    assert not any(line.lower().startswith("error:") for line in err)
    assert err[0] == "Checking bitrot.db integrity... ok."
    assert err[2] == "2 entries in the database. 1 entries renamed:"
    o3 = " from ./nonemptydirs/dir2/new-file-a.txt to ./nonemptydirs/dir2/new-file-a.txt2"
    assert err[3] == o3
    assert err[4] == "Updating bitrot.sha512... done."


@pytest.mark.order(5)
def test_deleted_files_in_a_tree_dir() -> None:
    assert bash(
        """
        rm  nonemptydirs/dir2/new-file-a.txt2
        """
    )
    rc, out, err = bitrot("-v")
    assert rc == 0
    assert not any(line.lower().startswith("error:") for line in err)
    assert err[0] == "Checking bitrot.db integrity... ok."
    assert err[2] == "1 entries in the database. 1 entries missing:"
    assert err[3] == "  ./nonemptydirs/dir2/new-file-a.txt2"
    assert err[4] == "Updating bitrot.sha512... done."


@pytest.mark.order(5)
def test_new_files_and_modified_files_in_a_tree_dir() -> None:
    assert bash(
        """
        for fil in {a,b,c,d,e,f,g}; do
            echo $fil >> more-files-$fil.txt
        done
        echo $RANDOM >> nonemptydirs/dir2/new-file-b.txt
        """
    )
    rc, out, err = bitrot("-v")
    assert rc == 0
    assert not any(line.lower().startswith("error:") for line in err)
    assert err[0] == "Checking bitrot.db integrity... ok."
    assert err[2] == "8 entries in the database. 7 entries new:"
    assert err[3] == "  ./more-files-a.txt"
    assert err[4] == "  ./more-files-b.txt"
    assert err[5] == "  ./more-files-c.txt"
    assert err[6] == "  ./more-files-d.txt"
    assert err[7] == "  ./more-files-e.txt"
    assert err[8] == "  ./more-files-f.txt"
    assert err[9] == "  ./more-files-g.txt"
    assert err[10] == "1 entries updated:"
    assert err[11] == "  ./nonemptydirs/dir2/new-file-b.txt"
    assert err[12] == "Updating bitrot.sha512... done."


@pytest.mark.order(6)
def test_new_files_modified_deleted_and_moved_in_a_tree_dir() -> None:
    assert bash(
        """
        for fil in {a,b,c,d,e,f,g}; do
            echo $fil $RANDOM >> nonemptydirs/pl-more-files-$fil.txt
        done
        echo $RANDOM >> nonemptydirs/dir2/new-file-b.txt
        mv more-files-a.txt more-files-a.txt2
        rm more-files-g.txt
        """
    )
    rc, out, err = bitrot("-v")
    assert rc == 0
    assert not any(line.lower().startswith("error:") for line in err)
    assert err[0] == "Checking bitrot.db integrity... ok."
    assert err[2] == "14 entries in the database. 7 entries new:"
    assert err[3] == "  ./nonemptydirs/pl-more-files-a.txt"
    assert err[4] == "  ./nonemptydirs/pl-more-files-b.txt"
    assert err[5] == "  ./nonemptydirs/pl-more-files-c.txt"
    assert err[6] == "  ./nonemptydirs/pl-more-files-d.txt"
    assert err[7] == "  ./nonemptydirs/pl-more-files-e.txt"
    assert err[8] == "  ./nonemptydirs/pl-more-files-f.txt"
    assert err[9] == "  ./nonemptydirs/pl-more-files-g.txt"
    assert err[10] == "1 entries updated:"
    assert err[11] == "  ./nonemptydirs/dir2/new-file-b.txt"
    assert err[12] == "1 entries renamed:"
    assert err[13] == " from ./more-files-a.txt to ./more-files-a.txt2"
    assert err[14] == "1 entries missing:"
    assert err[15] == "  ./more-files-g.txt"
    assert err[16] == "Updating bitrot.sha512... done."


{