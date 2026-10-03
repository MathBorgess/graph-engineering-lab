"""Legacy CLI: select one of the two native provider proxies."""
import argparse
import uvicorn
from .codex import app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend', choices=['codex', 'claude'], default='codex')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int)
    args = parser.parse_args()
    if args.backend == 'claude':
        from .claude import app as selected
        port = args.port or 8001
    else:
        selected = app
        port = args.port or 8000
    uvicorn.run(selected, host=args.host, port=port)


if __name__ == '__main__':
    main()
