"""
Serve your USB webcam as an MJPEG HTTP stream.

Requirements:
    pip install opencv-python

Usage:
    python webcam_mjpeg_server.py

Then set the VideoChannel stream_url in Django Admin to:
    http://localhost:8090/video

Pass --camera N to select a different camera index (default 0).
Pass --port N to change the port (default 8090).
"""

import argparse
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

try:
    import cv2
except ImportError:
    sys.exit("opencv-python is required: pip install opencv-python")

_frame_lock = threading.Lock()
_latest_frame: bytes = b""


def _capture_loop(cam_index: int) -> None:
    global _latest_frame
    cap = cv2.VideoCapture(cam_index, cv2.CAP_DSHOW)  # CAP_DSHOW = DirectShow on Windows
    if not cap.isOpened():
        sys.exit(f"Cannot open camera index {cam_index}")
    print(f"Camera {cam_index} opened — {int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))}x{int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))}")
    while True:
        ret, frame = cap.read()
        if not ret:
            continue
        _, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        with _frame_lock:
            _latest_frame = jpeg.tobytes()


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/video":
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.end_headers()
        try:
            while True:
                with _frame_lock:
                    frame = _latest_frame
                if frame:
                    self.wfile.write(
                        b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
                    )
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, fmt, *args):  # suppress per-request logs
        pass


def main():
    parser = argparse.ArgumentParser(description="Webcam MJPEG server")
    parser.add_argument("--camera", type=int, default=0, metavar="N")
    parser.add_argument("--port", type=int, default=8090, metavar="PORT")
    args = parser.parse_args()

    t = threading.Thread(target=_capture_loop, args=(args.camera,), daemon=True)
    t.start()

    server = HTTPServer(("0.0.0.0", args.port), _Handler)
    print(f"MJPEG stream running at  http://localhost:{args.port}/video")
    print("Set this as the stream_url on your VideoChannel in Django Admin.")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
