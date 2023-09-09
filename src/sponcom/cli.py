from click import group, command, argument

@group()
def main() -> None:
    """
    Sponsored Commit message generator.
    """

@main.command()
@argument("name")
def add(name: str) -> None:
    print("add", name)
