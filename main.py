import subprocess
import threading
import argparse
import os
import platform
import sys

# Paths
DJANGO_MANAGE_PATH = os.path.join(os.getcwd(), "manage.py")
VITE_DIR = os.path.join(os.getcwd(), "kjsitfeedbackvite")
IS_WINDOWS = platform.system() == "Windows"

# Commands
BACKEND_COMMAND = ["uv", "run", DJANGO_MANAGE_PATH, "runserver"]
FRONTEND_COMMAND = (
    f''
)

def stream_process(prefix, command, shell=False):
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        shell=shell,
        bufsize=1
    )
    for line in iter(process.stdout.readline, ''):
        print(f"[{prefix}] {line}", end='', flush=True)
    process.stdout.close()
    process.wait()

def run_migrations():
    print("[BACKEND] Running makemigrations and migrate with uv...")
    subprocess.run(["uv", "run", DJANGO_MANAGE_PATH, "makemigrations"], check=True)
    subprocess.run(["uv", "run", DJANGO_MANAGE_PATH, "migrate"], check=True)

def run_backend():
    print("Starting Django backend with uv...")
    run_migrations()
    stream_process("BACKEND", BACKEND_COMMAND)

def main():
    parser = argparse.ArgumentParser(description="Run frontend, backend, or both.")
    args = parser.parse_args()

    threads = []
    threads.append(threading.Thread(target=run_backend))

    for t in threads:
        t.start()
    for t in threads:
        t.join()

if __name__ == "__main__":
    main()

