from io import FileIO
import os
import zlib
import click
import hashlib


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
            if len(content) != int(size):
                raise RuntimeError(f"Invalid object {p}")
            print(content.decode("utf-8"), end="")


if __name__ == "__main__":
    git()
