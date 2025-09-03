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
    f'cmd.exe /c "cd {VITE_DIR} && npm run dev"' if IS_WINDOWS else ["npm", "run", "dev"]
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

def run_frontend():
    print("Starting Vite frontend...")
    shell = IS_WINDOWS
    stream_process("FRONTEND", FRONTEND_COMMAND, shell=shell)

def main():
    parser = argparse.ArgumentParser(description="Run frontend, backend, or both.")
    parser.add_argument("--frontend", action="store_true", help="Run Vite frontend only")
    parser.add_argument("--backend", action="store_true", help="Run Django backend only")
    args = parser.parse_args()

    threads = []
    if args.frontend and args.backend:
        threads.append(threading.Thread(target=run_backend))
        threads.append(threading.Thread(target=run_frontend))
    elif args.frontend:
        threads.append(threading.Thread(target=run_frontend))
    elif args.backend:
        threads.append(threading.Thread(target=run_backend))
    else:
        print("No arguments provided. Running both frontend and backend by default...")
        threads.append(threading.Thread(target=run_backend))
        threads.append(threading.Thread(target=run_frontend))

    for t in threads:
        t.start()
    for t in threads:
        t.join()

if __name__ == "__main__":
    main()

