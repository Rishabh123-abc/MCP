import os
import uuid
import subprocess

from pathlib import Path
from dotenv import load_dotenv

from fastmcp import FastMCP
from fastmcp.server.auth.providers.github import GitHubProvider

from starlette.applications import Starlette
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route, Mount


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

SERVER_URL = os.getenv(
    "BASE_URL",
    "https://manim-mcp-server-i1dc.onrender.com"
)

CLIENT_ID = os.getenv("GITHUB_CLIENT_ID")
CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET")

if not CLIENT_ID or not CLIENT_SECRET:
    raise RuntimeError(
        "Missing GITHUB_CLIENT_ID or GITHUB_CLIENT_SECRET"
    )

MANIM_QUALITY = {
    "low": "l",
    "medium": "m",
    "high": "h",
    "production": "p"
}


# ==========================================
# 3. GITHUB OAUTH AUTHENTICATION
# ==========================================

auth = GitHubProvider(
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    base_url=SERVER_URL,
    redirect_path="/auth/callback"
)


# ==========================================
# 4. INITIALIZE FASTMCP
# ==========================================

mcp = FastMCP(
    name="Remote Manim MCP Server",
    auth=auth
)


# ==========================================
# 5. MANIM RENDERING TOOL
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

        video_url = f"{SERVER_URL}/videos/{job_id}"

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
# 6. HEALTH CHECK
# ==========================================

async def health(request):
    return JSONResponse({
        "status": "online",
        "server": "Remote Manim MCP",
        "authentication": "GitHub OAuth"
    })


# ==========================================
# 7. VIDEO DOWNLOAD ENDPOINT
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
# 8. CREATE MCP HTTP APPLICATION
# ==========================================

mcp_app = mcp.http_app(path="/mcp")


# ==========================================
# 9. STARLETTE APPLICATION
# ==========================================

app = Starlette(
    routes=[
        Route("/health", health),
        Route("/videos/{job_id}", get_video),

        # OAuth discovery routes must be at the root.
        *auth.get_well_known_routes(mcp_path="/mcp"),

        # MCP and OAuth operational endpoints.
        Mount("/", app=mcp_app),
    ],
    lifespan=mcp_app.lifespan
)


# ==========================================
# 10. START SERVER
# ==========================================

if __name__ == "__main__":

    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000"))
    )