from io import FileIO
import os
import zlib
import click
import hashlib
import itertools


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
    m = hashlib.sha1()
    content = obj.read()
    blob = f"blob {len(content)}\0".encode("utf-8") + content
    m.update(blob)
    p = m.hexdigest()
    if w:
        path = f".git/objects/{p[0:2]}/{p[2:]}"
        folder = os.path.dirname(path)
        if not os.path.exists(folder):
            os.makedirs(folder)
        with open(path, "wb") as f:
            f.write(zlib.compress(blob))
    print(p)


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


if __name__ == "__main__":
    git()
