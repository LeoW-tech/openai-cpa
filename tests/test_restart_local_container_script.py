import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_SOURCE = REPO_ROOT / "scripts" / "restart_local_container.sh"
REBUILD_SOURCE = REPO_ROOT / "scripts" / "rebuild_local_container.sh"


class RestartLocalContainerScriptTests(unittest.TestCase):
    def _make_temp_project(self):
        temp_dir = tempfile.TemporaryDirectory()
        project_root = Path(temp_dir.name)
        scripts_dir = project_root / "scripts"
        data_dir = project_root / "data"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "config.yaml").write_text("demo: true\n", encoding="utf-8")

        restart_script = scripts_dir / "restart_local_container.sh"
        rebuild_script = scripts_dir / "rebuild_local_container.sh"
        restart_script.write_text(SCRIPT_SOURCE.read_text(encoding="utf-8"), encoding="utf-8")
        rebuild_script.write_text(REBUILD_SOURCE.read_text(encoding="utf-8"), encoding="utf-8")
        restart_script.chmod(restart_script.stat().st_mode | stat.S_IXUSR)
        rebuild_script.chmod(rebuild_script.stat().st_mode | stat.S_IXUSR)
        return temp_dir, project_root, restart_script

    def test_restart_uses_docker_restart_when_container_already_on_18000(self):
        temp_dir, project_root, restart_script = self._make_temp_project()
        self.addCleanup(temp_dir.cleanup)

        bin_dir = project_root / "fake-bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        log_file = project_root / "docker.log"
        fake_docker = bin_dir / "docker"
        fake_docker.write_text(
            "#!/usr/bin/env bash\n"
            "printf '%s\\n' \"$*\" >> \"$FAKE_DOCKER_LOG\"\n"
            "if [[ \"$1\" == inspect && \"$2\" == '-f' ]]; then\n"
            "  printf '%s\\n' \"${FAKE_DOCKER_INSPECT_PORT:-18000}\"\n"
            "  exit 0\n"
            "fi\n"
            "exit 0\n",
            encoding="utf-8",
        )
        fake_docker.chmod(fake_docker.stat().st_mode | stat.S_IXUSR)

        result = subprocess.run(
            ["/bin/bash", str(restart_script)],
            cwd=project_root,
            env={
                "HOME": os.environ["HOME"],
                "OPENAI_CPA_DOCKER_BIN": str(fake_docker),
                "PATH": f"{bin_dir}:/usr/bin:/bin",
                "FAKE_DOCKER_LOG": str(log_file),
                "FAKE_DOCKER_INSPECT_PORT": "18000",
            },
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        logged_commands = log_file.read_text(encoding="utf-8")
        self.assertIn("restart openai-cpa-local", logged_commands)
        self.assertNotIn("build -t openai-cpa-local:latest .", logged_commands)

    def test_restart_rebuilds_when_container_is_still_on_8000(self):
        temp_dir, project_root, restart_script = self._make_temp_project()
        self.addCleanup(temp_dir.cleanup)

        bin_dir = project_root / "fake-bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        log_file = project_root / "docker.log"
        fake_docker = bin_dir / "docker"
        fake_docker.write_text(
            "#!/usr/bin/env bash\n"
            "printf '%s\\n' \"$*\" >> \"$FAKE_DOCKER_LOG\"\n"
            "if [[ \"$1\" == inspect && \"$2\" == '-f' ]]; then\n"
            "  printf '%s\\n' \"${FAKE_DOCKER_INSPECT_PORT:-8000}\"\n"
            "  exit 0\n"
            "fi\n"
            "exit 0\n",
            encoding="utf-8",
        )
        fake_docker.chmod(fake_docker.stat().st_mode | stat.S_IXUSR)

        result = subprocess.run(
            ["/bin/bash", str(restart_script)],
            cwd=project_root,
            env={
                "HOME": os.environ["HOME"],
                "OPENAI_CPA_DOCKER_BIN": str(fake_docker),
                "PATH": f"{bin_dir}:/usr/bin:/bin",
                "FAKE_DOCKER_LOG": str(log_file),
                "FAKE_DOCKER_INSPECT_PORT": "8000",
            },
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        logged_commands = log_file.read_text(encoding="utf-8")
        self.assertIn("build -t openai-cpa-local:latest .", logged_commands)
        self.assertIn("--name openai-cpa-local -p 18000:8000", logged_commands)
        self.assertNotIn("restart openai-cpa-local", logged_commands)


if __name__ == "__main__":
    unittest.main()
