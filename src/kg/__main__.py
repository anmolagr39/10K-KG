"""Command line entry point.

    python -m kg download [--tickers AAPL MSFT] [--keep-raw]
    python -m kg build
    python -m kg ask "question" [--explain]
    python -m kg eval [--split test|dev]
"""
import argparse
import sys


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="python -m kg")
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("download", help="fetch latest 10-Ks from EDGAR and render them to PDF")
    d.add_argument("--tickers", nargs="*")
    d.add_argument("--keep-raw", action="store_true")
    b = sub.add_parser("build", help="extract facts from the PDFs and build the graph")
    b.add_argument("--tickers", nargs="*")
    b.add_argument("--stage", choices=["extract", "relations", "graph", "all"], default="all")
    a = sub.add_parser("ask", help="answer a question from the graph")
    a.add_argument("question")
    a.add_argument("--explain", action="store_true")
    c = sub.add_parser("chat", help="interactive: load the graph once, then ask questions")
    c.add_argument("--explain", action="store_true")
    e = sub.add_parser("eval", help="run the benchmark")
    e.add_argument("--split", default="test", choices=["test", "dev"])
    e.add_argument("--system", default="graph", choices=["graph", "bm25"])
    e.add_argument("--ids", nargs="*")
    args = p.parse_args(argv)

    if args.cmd == "download":
        from kg.build.download import run
        run(args.tickers, keep_raw=args.keep_raw)
    elif args.cmd == "build":
        from kg.build.pipeline import run
        run(args.tickers, stage=args.stage)
    elif args.cmd == "ask":
        from kg.query.answer import ask_cli
        ask_cli(args.question, explain=args.explain)
    elif args.cmd == "chat":
        from kg.query.answer import chat_cli
        chat_cli(explain=args.explain)
    elif args.cmd == "eval":
        from kg.eval.run_eval import run
        run(split=args.split, system=args.system, ids=args.ids)


if __name__ == "__main__":
    main(sys.argv[1:])
