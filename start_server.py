#!/usr/bin/env python3
import asyncio
import sys
import os
sys.path.insert(0, '/home/tork/browserapi-lab/browserapi_server')
os.chdir('/home/tork/browserapi-lab/browserapi_server')

from main import app
import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        log_level="info",
        timeout_keep_alive=300,
        timeout_graceful_shutdown=300,
        limit_concurrency=100,
        limit_max_requests=1000,
        reload=False
    )
