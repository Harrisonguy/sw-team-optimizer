"""
Entry point for the SW Team Rune Optimizer web app.

Usage
─────
    python run_optimizer.py [--port 5000] [--host 127.0.0.1]

Then open http://localhost:5000 in your browser.
"""
import argparse
import webbrowser
import threading
import time

def main():
    parser = argparse.ArgumentParser(description="SW Team Rune Optimizer")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--no-browser", action="store_true",
                        help="Do not automatically open the browser")
    args = parser.parse_args()

    from optimizer.app import app

    url = f"http://{args.host}:{args.port}"
    print("=" * 55)
    print("  SW Team Rune Optimizer")
    print(f"  Running at: {url}")
    print("  Press Ctrl+C to stop.")
    print("=" * 55)

    if not args.no_browser:
        def _open():
            time.sleep(1.2)
            webbrowser.open(url)
        threading.Thread(target=_open, daemon=True).start()

    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
