import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_SOURCE = REPO_ROOT / "scripts" / "rebuild_local_container.sh"


class RebuildLocalContainerScriptTests(unittest.TestCase):
    def _make_temp_project(self):
        temp_dir = tempfile.TemporaryDirectory()
        project_root = Path(temp_dir.name)
        scripts_dir = project_root / "scripts"
        data_dir = project_root / "data"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "config.yaml").write_text("demo: true\n", encoding="utf-8")

        script_path = scripts_dir / "rebuild_local_container.sh"
        script_path.write_text(SCRIPT_SOURCE.read_text(encoding="utf-8"), encoding="utf-8")
        script_path.chmod(script_path.stat().st_mode | stat.S_IXUSR)
        return temp_dir, project_root, script_path

    def test_script_reports_actionable_error_when_docker_is_missing(self):
        temp_dir, project_root, script_path = self._make_temp_project()
        self.addCleanup(temp_dir.cleanup)

        result = subprocess.run(
            ["/bin/bash", str(script_path)],
            cwd=project_root,
            env={
                "HOME": os.environ["HOME"],
                "OPENAI_CPA_DOCKER_BIN": str(project_root / "missing-docker"),
                "PATH": "/usr/bin:/bin",
            },
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("未找到 docker 命令", result.stderr)
        self.assertIn("/opt/homebrew/bin/docker", result.stderr)

    def test_script_rebuilds_container_when_docker_is_available(self):
        temp_dir, project_root, script_path = self._make_temp_project()
        self.addCleanup(temp_dir.cleanup)

        bin_dir = project_root / "fake-bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        log_file = project_root / "docker.log"
        fake_docker = bin_dir / "docker"
        fake_docker.write_text(
            "#!/usr/bin/env bash\n"
            "printf '%s\\n' \"$*\" >> \"$FAKE_DOCKER_LOG\"\n",
            encoding="utf-8",
        )
        fake_docker.chmod(fake_docker.stat().st_mode | stat.S_IXUSR)

        result = subprocess.run(
            ["/bin/bash", str(script_path)],
            cwd=project_root,
            env={
                "HOME": os.environ["HOME"],
                "OPENAI_CPA_DOCKER_BIN": str(fake_docker),
                "PATH": "/usr/bin:/bin",
                "FAKE_DOCKER_LOG": str(log_file),
            },
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertTrue(any(project_root.joinpath("data").glob("config.yaml.bak-*")))

        logged_commands = log_file.read_text(encoding="utf-8")
        self.assertIn("stop -t 15 openai-cpa-local", logged_commands)
        self.assertIn("rm -f openai-cpa-local", logged_commands)
        self.assertIn("build -t openai-cpa-local:latest .", logged_commands)
        self.assertIn("--name openai-cpa-local -p 18000:8000", logged_commands)
        self.assertIn("OPENAI_CPA_PUBLIC_HOST=127.0.0.1", logged_commands)
        self.assertIn("OPENAI_CPA_PUBLIC_PORT=18000", logged_commands)
        self.assertIn(f"HOST_PROJECT_PATH={project_root}", logged_commands)


if __name__ == "__main__":
    unittest.main()
