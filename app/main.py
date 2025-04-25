from io import FileIO, BytesIO
import os
import zlib
import click
import hashlib
import itertools
from datetime import datetime
import requests
import re


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
            objects.append(
                list(
                    itertools.chain(
                        *[x.split(b" ") for x in content[: pos + 21].split(b"\x00")]
                    )
                )
            )
            content = content[pos + 21 :]
        for o in objects:
            if name_only:
                print(o[1].decode("utf-8"))


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
def clone(url: str):
    host = "github.com"
    user = "cndoit18"
    repo = "codecrafters-git-python"

    resp = requests.get(
        f"https://{host}/{user}/{repo}/info/refs?service=git-upload-pack",
        headers={
            "user-agent": "git/2.47.0",
            "content-type": "application/x-git-upload-pack-request",
            "git-protocol": "version=1",
        },
    )
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
    # skip version
    cur += offset

    offset = int(smart[cur : cur + 4], base=16)
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

    for sha, _ in wants:
        data = f"0011command=fetch0001000fno-progress0032want {sha}\n0009done\n0000"
        resp = requests.post(
            f"https://{host}/{user}/{repo}/git-upload-pack",
            headers={
                "user-agent": "git/2.47.0",
                "content-type": "application/x-git-upload-pack-request",
                "git-protocol": "version=2",
            },
            data=data,
        )
        packfile = resp.content
        cur = 0
        offset = int(packfile[cur : cur + 4], base=16)

        cur += offset
        offset = int(packfile[cur : cur + 4], base=16)

        cur += 5
        assert packfile[cur : cur + 4] == "PACK".encode("utf-8")
        cur += 4
        # version
        assert 2 == int.from_bytes(packfile[cur : cur + 4], "big")


if __name__ == "__main__":
    git()
