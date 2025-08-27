import os
from fastapi import FastAPI
from fastapi.responses import JSONResponse
import asyncio

app = FastAPI(title="Bot Colosseum Health Check")

# Global variable to track if the bot is running
bot_running = False

@app.get("/health")
async def health_check():
    """Health check endpoint for Koyeb deployment"""
    status = {
        "status": "healthy" if bot_running else "starting",
        "bot_running": bot_running,
        "environment": os.getenv("ENV", "unknown"),
        "timestamp": asyncio.get_event_loop().time()
    }
    
    if bot_running:
        return JSONResponse(status, status_code=200)
    else:
        return JSONResponse(status, status_code=503)

@app.get("/ready")
async def readiness_check():
    """Readiness check endpoint"""
    if bot_running:
        return JSONResponse({"status": "ready"}, status_code=200)
    else:
        return JSONResponse({"status": "not ready"}, status_code=503)

def set_bot_running(status: bool):
    """Set the bot running status"""
    global bot_running
    bot_running = status
