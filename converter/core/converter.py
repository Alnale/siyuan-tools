import subprocess
import tempfile
import os


def _posix(path: str) -> str:
    return path.replace("\\", "/")


class PandocConverter:
    def __init__(self, pandoc_path: str = "pandoc"):
        self.pandoc_path = pandoc_path

    def check_pandoc_available(self) -> tuple[bool, str]:
        try:
            result = subprocess.run(
                [self.pandoc_path, "--version"],
                capture_output=True, text=True, encoding="utf-8"
            )
            version = result.stdout.split("\n")[0].strip()
            return True, version
        except FileNotFoundError:
            return False, "Pandoc not found. Please install pandoc: https://pandoc.org/installing.html"

    def convert(
        self,
        input_path: str,
        extract_media_dir: str | None = None,
    ) -> str:
        if not os.path.isfile(input_path):
            raise FileNotFoundError(f"Input file not found: {input_path}")

        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".md")
        os.close(tmp_fd)

        try:
            cmd = [
                self.pandoc_path,
                _posix(input_path),
                "-t", "markdown",
                "--wrap=none",
                "-o", _posix(tmp_path),
            ]

            if extract_media_dir:
                os.makedirs(extract_media_dir, exist_ok=True)
                cmd.append(f"--extract-media={_posix(extract_media_dir)}")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )

            if result.returncode != 0:
                raise RuntimeError(
                    f"Pandoc conversion failed (exit code {result.returncode}):\n{result.stderr}"
                )

            with open(tmp_path, "r", encoding="utf-8") as f:
                return f.read()

        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
