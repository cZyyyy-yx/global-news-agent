import threading
import time
import webbrowser

import server


def main() -> None:
    thread = threading.Thread(target=server.main, daemon=True)
    thread.start()
    time.sleep(1.5)
    webbrowser.open(f"http://127.0.0.1:{server.PORT}/")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        return


if __name__ == "__main__":
    main()
