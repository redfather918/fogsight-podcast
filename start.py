#!/usr/bin/env python3
"""
Fogsight Podcast 服务器启动脚本（非阻塞，立刻返回 PID）
Usage: python start.py [--port 8010] [--stop]
"""
import subprocess, sys, os, time, argparse, socket

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PY_PATH  = os.path.join(BASE_DIR, "venv", "Scripts", "python.exe")
PID_FILE = os.path.join(BASE_DIR, ".server.pid")
LOG_OUT  = os.path.join(BASE_DIR, "server.log")
LOG_ERR  = os.path.join(BASE_DIR, "server_err.log")


def is_port_free(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def find_free_port(start=8010, end=8099) -> int:
    for p in range(start, end):
        if is_port_free(p):
            return p
    raise RuntimeError("No free port found in range 8010-8099")


def stop():
    if not os.path.exists(PID_FILE):
        print("No PID file found.")
        return
    pid = int(open(PID_FILE).read().strip())
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(1, False, pid)
        if h:
            k32.TerminateProcess(h, 0)
            k32.CloseHandle(h)
            print(f"Stopped PID {pid}")
        else:
            print(f"PID {pid} not found (already stopped?)")
    except Exception as e:
        print(f"Error: {e}")
    os.remove(PID_FILE)


def start(port: int):
    if not is_port_free(port):
        print(f"Port {port} is busy, finding a free port...")
        port = find_free_port()
        print(f"Using port {port}")

    # 更新 config.py 端口
    cfg_file = os.path.join(BASE_DIR, "app", "config.py")
    cfg = open(cfg_file, encoding="utf-8").read()
    import re
    cfg2 = re.sub(r"app_port: int = \d+", f"app_port: int = {port}", cfg)
    open(cfg_file, "w", encoding="utf-8").write(cfg2)

    log_out = open(LOG_OUT, "w")
    log_err = open(LOG_ERR, "w")

    proc = subprocess.Popen(
        [PY_PATH, "run.py"],
        cwd=BASE_DIR,
        stdout=log_out,
        stderr=log_err,
        creationflags=0x00000008,  # DETACHED_PROCESS
    )
    open(PID_FILE, "w").write(str(proc.pid))

    # 等最多 10s 确认启动
    for i in range(10):
        time.sleep(1)
        if not is_port_free(port):
            log_out.flush()
            print(f"[OK] Server started on http://localhost:{port}  (PID {proc.pid})")
            return

    print(f"[WARN] Server may not have started. Check logs:")
    print(f"   {LOG_OUT}")
    print(f"   {LOG_ERR}")
    log_out.flush(); log_err.flush()
    tail = open(LOG_ERR, encoding="utf-8", errors="replace").read()[-800:]
    if tail:
        print("--- stderr ---")
        print(tail)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8010)
    ap.add_argument("--stop", action="store_true")
    args = ap.parse_args()

    if args.stop:
        stop()
    else:
        start(args.port)
