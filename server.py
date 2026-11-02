import os
import secrets
import uuid
import subprocess

from pathlib import Path
from dotenv import load_dotenv

from fastmcp import FastMCP

from starlette.applications import Starlette
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route, Mount
from starlette.middleware.base import BaseHTTPMiddleware


# ==========================================
# 1. LOAD ENVIRONMENT VARIABLES
# ==========================================

load_dotenv()

# ==========================================
# 2. CONFIGURATION
# ==========================================

BASE_DIR = Path(__file__).parent.resolve()

OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

MANIM_QUALITY = {
    "low": "l",
    "medium": "m",
    "high": "h",
    "production": "p"
}

# ==========================================
# 3. INITIALIZE FASTMCP
# ==========================================

mcp = FastMCP("Remote Manim MCP Server")


# ==========================================
# 4. MANIM RENDERING TOOL
# ==========================================

@mcp.tool()
def render_manim(
    scene_code: str,
    quality: str = "medium",
    scene_name: str = "MyScene"
) -> dict:
    """
    Render a Manim animation from Python scene code.

    Args:
        scene_code: Complete Python code containing a Manim Scene class.
        quality: low, medium, high, or production.
        scene_name: Name of the Scene class to render.
    """

    if quality not in MANIM_QUALITY:
        return {
            "success": False,
            "error": "Invalid quality"
        }

    if not scene_name.isidentifier():
        return {
            "success": False,
            "error": "Invalid scene name"
        }

    job_id = uuid.uuid4().hex

    job_dir = OUTPUT_DIR / job_id
    job_dir.mkdir(parents=True)

    script_path = job_dir / "scene.py"

    script_path.write_text(
        scene_code,
        encoding="utf-8"
    )

    command = [
        "manim",
        f"-q{MANIM_QUALITY[quality]}",
        "--media_dir",
        str(job_dir / "media"),
        str(script_path),
        scene_name
    ]

    try:

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=300,
            cwd=job_dir
        )

        if result.returncode != 0:
            return {
                "success": False,
                "error": result.stderr[-5000:],
                "job_id": job_id
            }

        videos = list(
            (job_dir / "media" / "videos").rglob("*.mp4")
        )

        if not videos:
            return {
                "success": False,
                "error": "Video not found after rendering"
            }

        video_path = videos[0]

        video_url = f"/videos/{job_id}"

        return {
            "success": True,
            "job_id": job_id,
            "video_url": video_url,
            "video_file": video_path.name,
            "message": "Manim animation rendered successfully"
        }

    except subprocess.TimeoutExpired:

        return {
            "success": False,
            "error": "Rendering timed out after 300 seconds"
        }

    except Exception as e:

        return {
            "success": False,
            "error": str(e)
        }


# ==========================================
# 5. HEALTH CHECK
# ==========================================

async def health(request):

    return JSONResponse({
        "status": "online",
        "server": "Remote Manim MCP"
    })


# ==========================================
# 6. VIDEO DOWNLOAD ENDPOINT
# ==========================================

async def get_video(request):

    job_id = request.path_params["job_id"]

    if (
        len(job_id) != 32
        or not all(c in "0123456789abcdef" for c in job_id)
    ):
        return JSONResponse(
            {"error": "Invalid job ID"},
            status_code=400
        )

    job_dir = OUTPUT_DIR / job_id

    videos = (
        list((job_dir / "media" / "videos").rglob("*.mp4"))
        if job_dir.exists()
        else []
    )

    if not videos:
        return JSONResponse(
            {"error": "Video not found"},
            status_code=404
        )

    return FileResponse(
        videos[0],
        media_type="video/mp4",
        filename="manim_animation.mp4"
    )


# ==========================================
# 7. STARLETTE APPLICATION
# ==========================================

app = Starlette(
    routes=[
        Route("/health", health),
        Route("/videos/{job_id}", get_video),
        Mount("/", app=mcp.http_app()),
    ]
)


# ==========================================
# 8. API KEY AUTHENTICATION
# ==========================================

class APIKeyMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request, call_next):

        # Health check remains public
        if request.url.path == "/health":
            return await call_next(request)

        expected_key = os.environ.get("MCP_API_KEY")

        if not expected_key:

            return JSONResponse(
                {"error": "Authentication not configured"},
                status_code=503
            )

        auth_header = request.headers.get(
            "Authorization", ""
        )

        supplied_key = (
            auth_header[7:].strip()
            if auth_header.startswith("Bearer ")
            else ""
        )

        if not secrets.compare_digest(
            supplied_key,
            expected_key
        ):

            return JSONResponse(
                {"error": "Unauthorized"},
                status_code=401
            )

        return await call_next(request)


app.add_middleware(APIKeyMiddleware)


# ==========================================
# 9. START SERVER
# ==========================================

if __name__ == "__main__":

    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000"))
    )