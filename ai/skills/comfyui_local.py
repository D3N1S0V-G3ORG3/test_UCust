"""
ComfyUILocalSkill - Local integration skill for ComfyUI Headless API (127.0.0.1:8188)
and CLI Runner integration for High-Quality Photorealistic Image Generation.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, Optional

try:
    from .comfy_cli_runner import ComfyCLIRunner
except ImportError:
    try:
        from skills.comfy_cli_runner import ComfyCLIRunner
    except ImportError:
        ComfyCLIRunner = None

logger = logging.getLogger("comfyui_local_skill")


class ComfyUILocalSkill:
    """
    Skill module for submitting Photo Generation workflow JSON graphs to local ComfyUI instance (http://127.0.0.1:8188)
    or CLI runner and fetching generated image files directly from local output directory.
    """

    def __init__(
        self,
        comfyui_url: Optional[str] = None,
        output_dir: Optional[str] = None,
        workflow_path: Optional[str] = None,
        timeout: float = 60.0,
    ) -> None:
        self.comfyui_url = (comfyui_url or os.getenv("COMFYUI_URL", "http://127.0.0.1:8188")).rstrip("/")
        self.output_dir = output_dir or os.getenv("COMFYUI_OUTPUT_DIR", os.path.abspath("./output/photos"))
        self.cli_runner = ComfyCLIRunner(
            comfyui_url=self.comfyui_url,
            output_dir=self.output_dir,
            workflow_template_path=workflow_path,
            timeout=timeout,
        )
        os.makedirs(self.output_dir, exist_ok=True)
        logger.info(
            "ComfyUILocalSkill initialized with Photo CLI Runner: server='%s', output_dir='%s'",
            self.comfyui_url,
            self.output_dir,
        )

    async def submit_workflow(self, workflow_graph: Dict[str, Any]) -> Dict[str, Any]:
        """
        Submits a ComfyUI JSON prompt graph to http://127.0.0.1:8188/prompt using CLI runner.
        """
        res = await self.cli_runner.execute_workflow(workflow_graph)
        return {"prompt_id": os.path.basename(res.get("photo_path", "job-1")), "media_info": res}

    async def fetch_generated_media(self, prompt_id: str) -> Dict[str, Optional[str]]:
        """
        Retrieves generated photo details from local output directory.
        """
        local_ppath = os.path.join(self.output_dir, f"qwen_photo_{prompt_id}.jpg")

        if not os.path.exists(local_ppath):
            return {
                "status": "no_image",
                "photo_path": None,
                "file_path": None,
                "image_url": None,
                "photo_url": None,
                "media_url": None,
            }

        return {
            "status": "success",
            "photo_path": local_ppath,
            "file_path": local_ppath,
            "image_url": f"/output/photos/{os.path.basename(local_ppath)}",
            "photo_url": f"/output/photos/{os.path.basename(local_ppath)}",
            "media_url": f"{self.comfyui_url}/view?filename={os.path.basename(local_ppath)}",
        }

    async def _execute_full_flow(self, workflow_graph: Dict[str, Any]) -> Dict[str, Optional[str]]:
        """
        Executes full CLI/API photo rendering flow and returns local file paths.
        """
        return await self.cli_runner.execute_workflow(workflow_graph)

    def generate_media_sync(self, workflow_graph: Dict[str, Any]) -> Dict[str, Optional[str]]:
        """
        Synchronous wrapper to submit workflow and return local media paths.
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    return pool.submit(asyncio.run, self._execute_full_flow(workflow_graph)).result()
            else:
                return loop.run_until_complete(self._execute_full_flow(workflow_graph))
        except Exception:
            return asyncio.run(self._execute_full_flow(workflow_graph))


__all__ = ["ComfyUILocalSkill"]
