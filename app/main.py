from io import FileIO, BytesIO
import os
import zlib
import click
import hashlib
import itertools
from datetime import datetime
import requests
import re
from urllib.parse import urlparse


@click.group()
def git():
    pass


@git.command()
def init():
    os.mkdir(".git")
    os.mkdir(".git/objects")
    os.mkdir(".git/refs")
    with open(".git/HEAD", "w") as f:
        f.write("ref: refs/heads/main\n")
    print("Initialized git directory")


@git.command(name="hash-object")
@click.option("-w", is_flag=True, help="write the object into the object database")
@click.argument("obj", type=click.File("rb"))
def hash_object(w: bool, obj: FileIO):
    print(_hash_object(w, obj, "blob"))


def _hash_object(w, obj, typ):
    m = hashlib.sha1()
    content = obj.read()
    blob = f"{typ} {len(content)}\0".encode("utf-8") + content
    m.update(blob)
    p = m.hexdigest()
    if w:
        path = f".git/objects/{p[0:2]}/{p[2:]}"
        folder = os.path.dirname(path)
        if not os.path.exists(folder):
            os.makedirs(folder)
        with open(path, "wb") as f:
            f.write(zlib.compress(blob))
    return p


@git.command(name="cat-file")
@click.option("-p", type=str, help="pretty-print <object> content")
def cat_file(p: str):
    if p:
        with open(f".git/objects/{p[0:2]}/{p[2:]}", "rb") as f:
            raw = zlib.decompress(f.read())
            head, content = raw.split(b"\0", 1)
            _, size = head.split(b" ")
            assert len(content) == int(size)
            print(content.decode("utf-8"), end="")


@git.command(name="ls-tree")
@click.argument("tree_ish", type=str)
@click.option("--name-only", is_flag=True, help="list only filenames")
def ls_tree(tree_ish: str, name_only: bool):
    with open(f".git/objects/{tree_ish[0:2]}/{tree_ish[2:]}", "rb") as f:
        raw = zlib.decompress(f.read())
        head, content = raw.split(b"\0", 1)
        assert head.startswith(b"tree")
        _, size = head.split(b" ")
        assert len(content) == int(size)
        objects = []
        while True:
            pos = content.find(b"\x00")
            if pos == -1:
                break
            x, sha1 = content[: pos + 21].split(b"\x00", 1)
            mode, name = x.split(b" ")
            objects.append([mode, name, sha1])
            content = content[pos + 21 :]
        for o in objects:
            if name_only:
                print(o[1].decode("utf-8"))
            else:
                print(
                    "{:0>6} {:040x}     {}".format(
                        o[0].decode("utf-8"),
                        int.from_bytes(o[2], "big"),
                        o[1].decode("utf-8"),
                    )
                )


@git.command(name="write-tree")
def write_tree():
    print(_write_tree())


def _write_tree(top=r".") -> str:
    files_hash = []
    for file in os.listdir(top):
        if file == ".git":
            continue

        path = os.path.join(top, file)
        if os.path.isfile(path):
            with open(path, "rb") as f:
                files_hash.append(
                    [
                        "100644",
                        os.path.relpath(path, start=top),
                        int(_hash_object(True, f, "blob"), base=16).to_bytes(
                            length=20,
                            byteorder="big",
                        ),
                    ]
                )
        elif os.path.isdir(os.path.join(top, file)):
            files_hash.append(
                [
                    "40000",
                    os.path.relpath(path, start=top),
                    int(
                        _write_tree(path),
                        base=16,
                    ).to_bytes(
                        length=20,
                        byteorder="big",
                    ),
                ]
            )
    files_hash.sort(key=lambda x: x[1])
    tree_blob = b"".join(
        f"{mode} {name}\0".encode("utf-8") + hash for mode, name, hash in files_hash
    )
    return _hash_object(True, BytesIO(tree_blob), "tree")


@git.command(name="commit-tree")
@click.argument("tree_ish", type=str)
@click.option("-p", type=str, help="id of a parent commit object")
@click.option("-m", type=str, help="commit message")
def commit_tree(tree_ish: str, p: str, m: str):
    now = datetime.now().astimezone()
    commit = f"tree {tree_ish} \n".encode("utf-8")
    if p:
        commit += f"parent {p} \n".encode("utf-8")
    commit += f"author cndoit18 <cndoit18@outlook.com> {int(now.timestamp())} {now.strftime('%z')}\n".encode(
        "utf-8"
    )
    commit += b"\n"
    if m:
        commit += m.encode("utf-8") + b"\n"
    print(_hash_object(True, BytesIO(commit), "commit"))


@git.command()
@click.argument("url", type=str)
@click.argument("target", type=str, required=False)
def clone(url: str, target: str):
    remote = urlparse(url)
    if not target:
        target = remote.path.split("/")[2]

    resp = requests.get(
        f"https://{remote.netloc}{remote.path}/info/refs?service=git-upload-pack",
        headers={
            "content-type": "application/x-git-upload-pack-request",
        },
    )
    assert resp.status_code == 200

    if not re.match(r"^[0-9a-f]{4}#", resp.text):
        click.echo("response format error")
    smart = resp.text
    cur = 0
    offset = int(smart[cur : cur + 4], base=16)

    # skip header
    cur += offset

    assert "0000" == smart[cur : cur + 4]
    cur += 4

    offset = int(smart[cur : cur + 4], base=16)

    if not os.path.exists(target):
        os.mkdir(target)
    os.chdir(target)
    os.mkdir(".git")
    os.mkdir(".git/objects")
    os.mkdir(".git/refs")
    ref = re.findall(r"symref=HEAD:(?P<ref>[^ ]*)", smart[cur + 4 : offset])
    hd, _ = smart[cur + 4 : offset].split(" ", 1)
    if ref:
        with open(".git/HEAD", "w") as f:
            f.write(f"ref: {ref[0]}")

    # skip metadata
    cur += offset

    wants = []
    while cur < len(smart):
        offset = int(smart[cur : cur + 4], base=16)
        if offset == 0:
            break
        sha, ref = smart[cur + 4 : cur + offset - 1].split(" ")
        wants.append([sha, ref])
        cur += offset

    for sha, ref in wants:
        ref = os.path.join(".git", ref)
        os.mkdir(os.path.dirname(ref))
        with open(ref, "w") as f:
            f.write(sha)
        data = f"0032want {sha}\n00000009done\n"
        resp = requests.post(
            f"https://{remote.netloc}{remote.path}/git-upload-pack",
            headers={
                "content-type": "application/x-git-upload-pack-request",
            },
            data=data,
        )
        assert resp.status_code == 200
        nak, packfile = resp.content.split(b"\n", 1)
        assert nak[4:] == b"NAK"
        assert packfile[-20:] == hashlib.sha1(packfile[:-20]).digest()
        cur = 0
        assert packfile[cur : cur + 4] == b"PACK"
        cur += 4
        assert int.from_bytes(packfile[cur : cur + 4], "big") == 2
        cur += 4
        obj_len = int.from_bytes(packfile[cur : cur + 4])
        cur += 4
        pack = packfile[cur:]

        deltas = []
        for _ in range(obj_len):
            byte = pack[0]
            obj_type = (byte >> 4) & 0x07
            size = byte & 0x0F
            shift = 4
            pack = pack[1:]
            while byte & 0x80 and len(pack) > 0:
                byte = pack[0]
                size |= (byte & 0x7F) << shift
                shift += 7
                pack = pack[1:]
            decompressor = zlib.decompressobj()
            if obj_type in {1: "commit", 2: "tree", 3: "blob"}:
                raw = decompressor.decompress(pack, max_length=size)
                decompressor.flush()
                assert len(raw) == size
                _hash_object(
                    True,
                    BytesIO(raw),
                    {1: "commit", 2: "tree", 3: "blob"}[obj_type],
                )
            else:
                delta_name, pack = pack[0:20], pack[20:]
                raw = decompressor.decompress(pack, max_length=size)
                decompressor.flush()
                assert len(raw) == size
                deltas.append(
                    (
                        delta_name.hex(),
                        raw,
                    )
                )

            pack = decompressor.unused_data

        for delta in deltas:
            raw = delta[1]
            sha = delta[0]

            source_size, raw = process_var_int(raw)
            target_size, raw = process_var_int(raw)
            target_content = b""

            with open(f".git/objects/{sha[0:2]}/{sha[2:]}", "rb") as f:
                original = zlib.decompress(f.read())
                head, content = original.split(b"\0", 1)
                typ, si = head.split(b" ")
                assert len(content) == int(si)
                assert source_size == int(si)

            while raw:
                byte = raw[0]
                raw = raw[1:]
                if byte & 0x80:  # copy
                    offset = 0
                    size = 0
                    shift = 0
                    offset_bits = byte & 0xF
                    while offset_bits:
                        if offset_bits & 1:
                            offset |= raw[0] << shift
                            raw = raw[1:]
                        shift += 8
                        offset_bits = offset_bits >> 1
                    shift = 0
                    size_bits = (byte >> 4) & 0x7
                    while size_bits:
                        if size_bits & 1:
                            size |= raw[0] << shift
                            raw = raw[1:]
                        shift += 8
                        size_bits = size_bits >> 1
                    size = size or 0x1000
                    assert offset + size <= source_size
                    target_content += content[offset : offset + size]
                else:  # insert
                    size = byte & 0x7F
                    data, raw = raw[:size], raw[size:]
                    assert len(data) == size
                    target_content += data
            assert len(target_content) == target_size
            _hash_object(True, BytesIO(target_content), typ)

    # init workspace
    with open(f".git/objects/{hd[0:2]}/{hd[2:]}", "rb") as f:
        raw = zlib.decompress(f.read())
        index = raw.find(b"tree ")
        tree_ish = raw[index + 5 : index + 45]
        _write_workspace(tree_ish.decode("utf-8"))


def _write_workspace(tree_ish, top="."):
    with open(f".git/objects/{tree_ish[:2]}/{tree_ish[2:]}", "rb") as f:
        raw = zlib.decompress(f.read())
        head, content = raw.split(b"\0", 1)
        assert head.startswith(b"tree")
        _, size = head.split(b" ")
        assert len(content) == int(size)
        while True:
            pos = content.find(b"\x00")
            if pos == -1:
                break
            x, sha1 = content[: pos + 21].split(b"\x00", 1)
            mode, name = x.split(b" ")
            content = content[pos + 21 :]
            sha1 = sha1.hex()
            path = os.path.join(top, name.decode("utf-8"))
            mode = int(mode, 8)
            if mode & 0x4000:
                if not os.path.exists(path):
                    os.mkdir(path)
                _write_workspace(sha1, top=path)
            else:
                with open(f".git/objects/{sha1[0:2]}/{sha1[2:]}", "rb") as f:
                    raw = zlib.decompress(f.read())
                    head, cc = raw.split(b"\0", 1)
                    _, size = head.split(b" ")
                    assert len(cc) == int(size)
                with open(path, "w") as f:
                    f.write(cc.decode())
                os.chmod(path, mode & 0x1FF)
                continue


def process_var_int(raw):
    shift = 0
    var = 0
    while raw[0] & 0x80:
        c, raw = raw[0], raw[1:]
        var |= (c & 0x7F) << shift
        shift += 7
    c, raw = raw[0], raw[1:]
    var += (c & 0x7F) << shift
    return var, raw


if __name__ == "__main__":
    git()
