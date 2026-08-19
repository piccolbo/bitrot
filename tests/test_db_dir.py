import os
import sys
from pathlib import Path

import pytest

# Ensure src is importable
SRC = Path(__file__).resolve().parents[1] / 'src'
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import bitrot


def test_get_path_and_db_dir(tmp_path):
    db_dir = tmp_path
    db_dir_b = str(db_dir).encode(bitrot.FSENCODING)
    p = bitrot.get_path(directory=db_dir_b)
    assert p == os.path.join(db_dir_b, b'.bitrot.db')


def test_stable_sum_and_integrity(tmp_path):
    old_cwd = os.getcwd()
    try:
        os.chdir(str(tmp_path))
        db_dir_b = str(tmp_path).encode(bitrot.FSENCODING)
        bitrot_db = bitrot.get_path(directory=db_dir_b)
        conn = bitrot.get_sqlite3_cursor(bitrot_db)
        cur = conn.cursor()
        # create a file and insert into DB with the path format collect_paths produces
        (tmp_path / 'a.txt').write_text('hello')
        sha = bitrot.sha1(os.path.join(b'.', b'a.txt'), bitrot.DEFAULT_CHUNK_SIZE)
        p_stored = bitrot.normalize_path(os.path.join(b'.', b'a.txt'))
        cur.execute('INSERT INTO bitrot VALUES (?, ?, ?, ?)', (p_stored, 1, sha, bitrot.ts()))
        conn.commit()

        sum1 = bitrot.stable_sum(bitrot_db=bitrot_db)
        assert isinstance(sum1, str) and len(sum1) == 128

        # write .bitrot.sha512 to match current DB
        bitrot.update_sha512_integrity(verbosity=0, db_dir=db_dir_b)

        # modify DB so integrity check fails
        cur.execute('INSERT INTO bitrot VALUES (?, ?, ?, ?)', (p_stored + '2', 2, sha, bitrot.ts()))
        conn.commit()

        with pytest.raises(bitrot.BitrotException):
            bitrot.check_sha512_integrity(verbosity=0, db_dir=db_dir_b)

        # update should make it consistent again
        bitrot.update_sha512_integrity(verbosity=0, db_dir=db_dir_b)
        bitrot.check_sha512_integrity(verbosity=0, db_dir=db_dir_b)

    finally:
        os.chdir(old_cwd)


def test_run_with_db_dir(tmp_path):
    old_cwd = os.getcwd()
    try:
        db_dir = tmp_path
        db_dir_b = str(db_dir).encode(bitrot.FSENCODING)
        # create a file to be tracked
        (db_dir / 'file1.txt').write_text('data')
        os.chdir(str(db_dir))

        bitrot_db = bitrot.get_path(directory=db_dir_b)
        conn = bitrot.get_sqlite3_cursor(bitrot_db)
        cur = conn.cursor()

        # sha1 of the relative path as seen by collect_paths (./file1.txt)
        sha = bitrot.sha1(os.path.join(b'.', b'file1.txt'), bitrot.DEFAULT_CHUNK_SIZE)
        p_stored = bitrot.normalize_path(os.path.join(b'.', b'file1.txt'))
        cur.execute('INSERT INTO bitrot VALUES (?, ?, ?, ?)', (p_stored, int(os.stat('file1.txt').st_mtime), sha, bitrot.ts()))
        conn.commit()

        bt = bitrot.Bitrot(verbosity=0, test=True)
        # run should complete without raising
        bt.run(roots=[b'.'], recursive=True, db_dir=db_dir_b)

    finally:
        os.chdir(old_cwd)
