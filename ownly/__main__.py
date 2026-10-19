"""Run Ownly, or add example listings.

    .venv/bin/python -m ownly                  # serve on http://127.0.0.1:8720
    .venv/bin/python -m ownly --port 9000
    .venv/bin/python -m ownly seed             # add example listings built from real Ames sales
"""
import argparse

from . import create_app, seed


def main() -> None:
    parser = argparse.ArgumentParser(prog="ownly", description="Ownly: homes sold by their owners in Ames.")
    parser.add_argument("command", nargs="?", default="serve", choices=["serve", "seed"])
    parser.add_argument("--port", type=int, default=8720)
    parser.add_argument("--count", type=int, default=12, help="example listings to add with 'seed'")
    args = parser.parse_args()
    app = create_app()
    if args.command == "seed":
        with app.app_context():
            print(f"Added {seed.add_examples(args.count)} example listings.")
        return
    # Loopback only: put a TLS reverse proxy in front before letting anyone else in.
    app.run(host="127.0.0.1", port=args.port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
