# cli.py — CLI removed in simplification.
# This module is kept as a stub for backward compatibility.


def main_make_alias():
    """command alias
    hmake = httprunner make
    """
    sys.argv.insert(1, "make")
    main()


if __name__ == "__main__":
    main()
