"""Command line: `supermairio play`, `supermairio bench` and `supermairio replay`."""

import argparse

from supermairio import __version__


def build_parser(env: dict[str, str]) -> tuple[argparse.ArgumentParser, argparse.ArgumentParser]:
    from supermairio.benchmark import edition, replay
    from supermairio.config import play_parser

    parser = argparse.ArgumentParser(prog="supermairio",
        description="A real-time benchmark for System 1 decision models, played on Super Mario Bros 1-1.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    play = play_parser(env, commands.add_parser("play", help="play with a model, the demo or the keyboard"))
    bench = commands.add_parser("bench", help="run, report and verify a benchmark edition",
        description="Run, report and verify a benchmark edition.")
    edition.add_arguments(bench)
    replay.add_arguments(commands.add_parser("replay", help="render a recorded episode as an animated GIF",
        description="Replay a recorded episode offline and save it as an animated GIF."))
    return parser, play


def main(argv: list[str] | None = None) -> int:
    from supermairio.config import environment, play_config

    env = environment()
    parser, play = build_parser(env)
    args = parser.parse_args(argv)
    if args.command == "play":
        from supermairio.runtime.play import start

        return start(play_config(play, args, env))
    if args.command == "bench":
        from supermairio.benchmark.edition import run

        return run(args)
    from supermairio.benchmark.replay import run

    return run(args)
