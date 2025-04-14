import sys
import os
import zlib


def main():
    command = sys.argv[1]
    if command == "init":
        os.mkdir(".git")
        os.mkdir(".git/objects")
        os.mkdir(".git/refs")
        with open(".git/HEAD", "w") as f:
            f.write("ref: refs/heads/main\n")
        print("Initialized git directory")

    elif command == "cat-file" and sys.argv[2] == "-p":
        path = sys.argv[3]
        with open(f".git/objects/{path[0:2]}/{path[2:]}", "rb") as f:
            raw = zlib.decompress(f.read())
            head, content = raw.split(b"\0", 1)
            _, size = head.split(b" ")
            if len(content) != int(size):
                raise RuntimeError(f"Invalid object {path}")
            print(content.decode("utf-8"), end="")
    else:
        raise RuntimeError(f"Unknown command #{command}")


if __name__ == "__main__":
    main()
