"""Detached retained-operation worker; invoked only by collaboration._spawn."""

import argparse

from .collaboration import run_worker


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True)
    parser.add_argument("--operation", required=True)
    args = parser.parse_args(argv)
    run_worker(args.state, args.operation)


if __name__ == "__main__":
    main()
