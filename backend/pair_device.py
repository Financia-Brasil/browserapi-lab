#!/usr/bin/env python3
"""Pareia somente o Farol Beta depurável via USB. Nunca copia a chave OpenAI."""
import argparse
import json
import os
import subprocess
from farol_backend import load_env


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial", required=True)
    parser.add_argument("--env", required=True)
    args = parser.parse_args()
    load_env(args.env)
    token = os.environ.get("FAROL_DEVICE_TOKEN", "")
    if len(token) < 24:
        raise SystemExit("Token de pareamento ausente")
    port = int(os.environ.get("FAROL_PORT", "8765"))
    adb = ["adb", "-s", args.serial]
    subprocess.run(adb + ["reverse", f"tcp:{port}", f"tcp:{port}"], check=True, capture_output=True)
    payload = json.dumps({"endpoint": f"http://127.0.0.1:{port}/v1/assist", "token": token})
    subprocess.run(adb + ["shell", "run-as", "com.ifpa.iassistente.beta", "mkdir", "-p", "files"], check=True, capture_output=True)
    subprocess.run(adb + ["shell", "run-as", "com.ifpa.iassistente.beta", "tee", "files/ai-connection.json"], input=payload, text=True, check=True, capture_output=True)
    subprocess.run(adb + ["shell", "run-as", "com.ifpa.iassistente.beta", "chmod", "600", "files/ai-connection.json"], check=True, capture_output=True)
    print("Farol Beta pareado por USB; chave OpenAI permanece no computador.")


if __name__ == "__main__":
    main()
