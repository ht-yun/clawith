"""Agent lifecycle manager — Docker container management for OpenClaw Gateway instances."""

import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.llm import LLMModel
from app.services.llm import get_model_api_key

settings = get_settings()

# Lazy-loaded Docker exception classes (only when docker is available)
_docker_available = False
_DockerException = Exception
_NotFound = Exception

try:
    import docker
    from docker.errors import DockerException as _DockerException, NotFound as _NotFound
    _docker_available = True
except ImportError:
    pass


class AgentManager:
    """Manage OpenCode Gateway Docker containers for digital employees."""

    def __init__(self):
        if _docker_available:
            try:
                self.docker_client = docker.from_env()
            except _DockerException:
                logger.warning("Docker not available — agent containers will not be managed")
                self.docker_client = None
        else:
            self.docker_client = None

    def _agent_dir(self, agent_id: uuid.UUID) -> Path:
        return Path(settings.AGENT_DATA_DIR) / str(agent_id)

    def _template_dir(self) -> Path:
        return Path(settings.AGENT_TEMPLATE_DIR)

    def _env_for_agent(self, agent_id: uuid.UUID, model: LLMModel) -> dict:
        api_key = get_model_api_key(model)
        env = {
            "AGENT_ID": str(agent_id),
            "LLM_PROVIDER": model.provider,
            "LLM_MODEL": model.model,
            "LLM_API_KEY": api_key,
            "LLM_BASE_URL": model.base_url or "",
            "OPENCODE_GATEWAY_PORT": str(settings.OPENCODE_GATEWAY_PORT),
            "OPENCODE_IMAGE": settings.OPENCODE_IMAGE,
        }
        return env

    async def initialize_agent_files(
        self,
        db: AsyncSession,
        agent,
        personality: str = "",
        boundaries: str = "",
    ):
        """Initialize an agent's file workspace from the template directory.

        For native agents, copies the template skeleton into the agent's data dir.
        For opencode agents, this is a no-op (no file workspace needed).
        """
        agent_dir = self._agent_dir(agent.id)
        agent_dir.mkdir(parents=True, exist_ok=True)

        template_dir = self._template_dir()
        if template_dir.exists():
            # Copy template files (shutil.copytree with dirs_exist_ok for py3.8+)
            shutil.copytree(template_dir, agent_dir, dirs_exist_ok=True)

        # Write soul.md from personality + boundaries
        soul = agent_dir / "soul.md"
        if personality or boundaries:
            content = ""
            if personality:
                content += f"# Personality\n\n{personality}\n\n"
            if boundaries:
                content += f"# Boundaries\n\n{boundaries}\n"
            soul.write_text(content, encoding="utf-8")

        # Write memory.md skeleton
        memory = agent_dir / "memory.md"
        if not memory.exists():
            memory.write_text("# Long-term Memory\n\n", encoding="utf-8")

        # Write HEARTBEAT.md skeleton
        heartbeat = agent_dir / "HEARTBEAT.md"
        if not heartbeat.exists():
            from app.services.heartbeat import DEFAULT_HEARTBEAT_INSTRUCTION
            heartbeat.write_text(DEFAULT_HEARTBEAT_INSTRUCTION, encoding="utf-8")

        logger.info(f"Initialized agent workspace at {agent_dir}")

    async def _write_soul_and_memory(
        self,
        db: AsyncSession,
        agent,
        personality: str = "",
        boundaries: str = "",
    ):
        """Write or update soul.md and memory.md for an existing agent."""
        agent_dir = self._agent_dir(agent.id)
        agent_dir.mkdir(parents=True, exist_ok=True)
        soul_path = agent_dir / "soul.md"
        content = ""
        if personality:
            content += f"# Personality\n\n{personality}\n\n"
        if boundaries:
            content += f"# Boundaries\n\n{boundaries}\n"
        if content:
            soul_path.write_text(content, encoding="utf-8")
        memory_path = agent_dir / "memory.md"
        if not memory_path.exists():
            memory_path.write_text("# Long-term Memory\n\n", encoding="utf-8")

    # ── Docker container management ──

    def _local_ip(self) -> str:
        """Best-effort local machine IP for container-to-gateway routing."""
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    async def start_container(
        self,
        db: AsyncSession,
        agent,
        model: LLMModel = None,
    ) -> str | None:
        """Create and start a Docker container for the given agent.

        Returns the container ID on success, None on failure.
        If model is not provided, it is looked up from the agent's primary model.
        """
        if not self.docker_client:
            logger.warning(f"Docker not available — skipping container start for {agent.name}")
            agent.status = "idle"
            return None

        # Resolve model if not provided
        if model is None:
            model_id = agent.primary_model_id or agent.fallback_model_id
            if not model_id:
                logger.error(f"No LLM model configured for agent {agent.name}")
                return None
            result = await db.execute(select(LLMModel).where(LLMModel.id == model_id))
            model = result.scalar_one_or_none()
            if not model:
                logger.error(f"LLM model {model_id} not found for agent {agent.name}")
                return None

        # Ensure the agent data directory exists
        agent_dir = self._agent_dir(agent.id)
        agent_dir.mkdir(parents=True, exist_ok=True)

        # Write env file for the container
        env = self._env_for_agent(agent.id, model)
        env_path = agent_dir / ".env"
        with open(env_path, "w") as f:
            for k, v in env.items():
                f.write(f"{k}={v}\n")

        image = settings.OPENCODE_IMAGE
        gateway_port = settings.OPENCODE_GATEWAY_PORT
        container_port = self._find_free_port(gateway_port)

        try:
            # Pull the image first
            try:
                self.docker_client.images.get(image)
            except _NotFound:
                logger.info(f"Pulling image {image}...")
                self.docker_client.images.pull(image)

            container = self.docker_client.containers.run(
                image=image,
                detach=True,
                ports={"3000/tcp": container_port},
                volumes={
                    str(agent_dir): {"bind": "/workspace", "mode": "rw"},
                    str(env_path): {"bind": "/workspace/.env", "mode": "ro"},
                },
                environment={
                    "GATEWAY_URL": f"http://{self._local_ip()}:{gateway_port}",
                },
                name=f"opencode-agent-{agent.id}",
                network=settings.DOCKER_NETWORK,
                restart_policy={"Name": "unless-stopped"},
            )

            agent.container_id = container.id
            agent.container_port = container_port
            agent.status = "running"
            agent.last_active_at = datetime.now(timezone.utc)

            logger.info(f"Started container {container.id[:12]} for agent {agent.name} on port {container_port}")
            return container.id

        except _DockerException as e:
            logger.error(f"Failed to start container for agent {agent.name}: {e}")
            agent.status = "error"
            return None

    async def stop_container(self, agent) -> bool:
        """Stop and remove the agent's Docker container."""
        if not self.docker_client or not agent.container_id:
            return True

        try:
            container = self.docker_client.containers.get(agent.container_id)
            container.stop(timeout=10)
            agent.status = "stopped"
            logger.info(f"Stopped container {agent.container_id[:12]} for agent {agent.name}")
            return True
        except _NotFound:
            agent.status = "stopped"
            agent.container_id = None
            return True
        except _DockerException as e:
            logger.error(f"Failed to stop container: {e}")
            return False

    async def remove_container(self, agent) -> bool:
        """Force-remove the agent's Docker container."""
        if not self.docker_client or not agent.container_id:
            return True

        try:
            container = self.docker_client.containers.get(agent.container_id)
            container.remove(force=True)
            agent.container_id = None
            agent.container_port = None
            logger.info(f"Removed container for agent {agent.name}")
            return True
        except _NotFound:
            agent.container_id = None
            return True
        except _DockerException as e:
            logger.error(f"Failed to remove container: {e}")
            return False

    def container_status(self, agent) -> dict:
        """Get current status of the agent's container."""
        if not self.docker_client or not agent.container_id:
            return {"running": False, "status": "not_found"}

        try:
            container = self.docker_client.containers.get(agent.container_id)
            return {
                "running": container.status == "running",
                "status": container.status,
                "ports": container.ports,
                "created": container.attrs.get("Created", ""),
            }
        except _NotFound:
            return {"running": False, "status": "not_found"}
        except _DockerException:
            return {"running": False, "status": "error"}

    def _find_free_port(self, base_port: int) -> int:
        """Find a free port starting from base_port."""
        import socket
        port = base_port
        while True:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                s.bind(("0.0.0.0", port))
                s.close()
                return port
            except OSError:
                port += 1
                if port > base_port + 100:
                    return base_port  # Fallback
                s.close()


agent_manager = AgentManager()
